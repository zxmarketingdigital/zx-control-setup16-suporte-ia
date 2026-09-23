#!/usr/bin/env python3
"""Auditoria técnica final do Setup 16."""
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comum import cfg_get, http_json, load_config, supabase_rest

ROOT = Path(__file__).resolve().parents[1]


def check(nome, func):
    try:
        ok, detalhe = func()
        return bool(ok), nome, str(detalhe)
    except Exception as exc:
        return False, nome, "erro: %s" % exc


def http_base(config):
    return str(cfg_get(config, "supabase_url", "")).rstrip("/")


def tabelas(config):
    nomes = ("sup_equipe", "sup_config", "sup_tickets", "sup_mensagens", "sup_kb", "sup_kb_candidatas", "sup_uso_ia")
    falhas = []
    for nome in nomes:
        status, dados = supabase_rest(config, "GET", "/%s?select=*&limit=1" % nome)
        if status < 200 or status >= 300:
            falhas.append("%s HTTP %s" % (nome, status))
    return not falhas, "tabelas respondem" if not falhas else "; ".join(falhas)


def rls_anon(config):
    base = http_base(config)
    anon = cfg_get(config, "supabase_anon_key", "")
    if not base or not anon:
        return False, "URL ou anon key ausente"
    status, dados = http_json(
        "GET",
        base + "/rest/v1/sup_tickets?select=id&limit=1",
        headers={"apikey": anon, "Authorization": "Bearer " + str(anon)},
    )
    aceito = status == 401 or (status == 200 and dados == [])
    return aceito, "anon bloqueado (HTTP %s)" % status if aceito else "anon retornou dados ou erro inesperado (HTTP %s)" % status


def funcao(config, acao):
    base = http_base(config)
    anon = cfg_get(config, "supabase_anon_key", "")
    if not base:
        return False, "Supabase URL ausente"
    headers = {"Content-Type": "application/json"}
    if anon:
        headers["apikey"] = str(anon)
    corpo = {"acao": acao}
    if acao == "mensagem":
        corpo.update({"canal": "site", "conversa_id": "auditoria-setup", "mensagem": "Mensagem de teste da auditoria"})
    status, dados = http_json("POST", base + "/functions/v1/support-ai", headers=headers, corpo=corpo)
    if acao == "ping":
        return status == 200 and isinstance(dados, dict) and dados.get("ok") is True, "ping HTTP %s" % status
    return status == 200 and isinstance(dados, dict) and "resposta" in dados, "mensagem HTTP %s" % status


def hub(config):
    suporte = config.get("suporte") if isinstance(config.get("suporte"), dict) else {}
    url = str(suporte.get("hub_url", "")).rstrip("/")
    if not url:
        return False, "hub_url ausente"
    status, corpo = http_json("GET", url)
    ok = status == 200 and isinstance(corpo, str) and "<html" in corpo.lower()
    return ok, "hub HTTP %s" % status


def widget(config):
    suporte = config.get("suporte") if isinstance(config.get("suporte"), dict) else {}
    url = str(suporte.get("hub_url", "")).rstrip("/")
    if not url:
        return False, "hub_url ausente"
    status, corpo = http_json("GET", url + "/suporte-widget.js")
    return status == 200 and isinstance(corpo, str) and ("attachShadow" in corpo or "shadow" in corpo.lower()), "widget HTTP %s" % status


def admin(config):
    status, dados = supabase_rest(config, "GET", "/sup_equipe?papel=eq.admin&select=user_id&limit=1")
    return status == 200 and isinstance(dados, list) and len(dados) >= 1, "admin encontrado" if isinstance(dados, list) and dados else "nenhum admin"


def kb(config):
    status, dados = supabase_rest(config, "GET", "/sup_kb?ativo=eq.true&select=id&limit=1000")
    quantidade = len(dados) if isinstance(dados, list) else 0
    return status == 200 and quantidade >= 5, "%s itens ativos" % quantidade


def agendamento():
    sys.path.insert(0, str(ROOT / "setup"))
    import agendador
    resultado = agendador.status(sistema=platform.system())
    return resultado.get("ok") is True, resultado.get("detalhe", "sem detalhe")


def evolution(config):
    base = cfg_get(config, "evolution_url", "")
    instancia = cfg_get(config, "evolution_instance", "")
    chave = cfg_get(config, "evolution_api_key", "")
    if not base or not instancia:
        return True, "Evolution não configurada; canal site permanece disponível"
    if not chave:
        return False, "Evolution configurada sem chave"
    status, dados = http_json(
        "GET",
        str(base).rstrip("/") + "/webhook/find/" + str(instancia),
        headers={"apikey": str(chave)},
    )
    suporte = str((cfg_get(config, "supabase_url", "") or "")).rstrip("/") + "/functions/v1/support-ai"
    texto = str(dados)
    return status == 200 and suporte in texto, "webhook conferido" if status == 200 and suporte in texto else "webhook não aponta para support-ai"


def segredo_front():
    caminho = ROOT / "hub" / "config.js"
    if not caminho.exists():
        return True, "hub/config.js ainda não existe no repositório"
    conteudo = caminho.read_text(encoding="utf-8", errors="replace")
    proibidos = ("service_role", "sk-", "AIza")
    encontrados = [item for item in proibidos if item in conteudo]
    return not encontrados, "nenhum segredo encontrado" if not encontrados else "marcadores proibidos: %s" % ", ".join(encontrados)


def main():
    config = load_config()
    testes = [
        ("Tabelas Supabase", lambda: tabelas(config)),
        ("RLS para anon", lambda: rls_anon(config)),
        ("Função ping", lambda: funcao(config, "ping")),
        ("Mensagem de teste", lambda: funcao(config, "mensagem")),
        ("Hub HTTP", lambda: hub(config)),
        ("Widget acessível", lambda: widget(config)),
        ("Membro admin", lambda: admin(config)),
        ("KB mínima", lambda: kb(config)),
        ("Agendamento", agendamento),
        ("Webhook Evolution", lambda: evolution(config)),
        ("Segredos no hub", segredo_front),
    ]
    falhas = 0
    print("Etapa 7 — auditoria técnica final")
    for nome, func in testes:
        ok, rotulo, detalhe = check(nome, func)
        print("%-24s %s %s" % (rotulo, "OK" if ok else "FALHA", detalhe))
        if not ok:
            falhas += 1
    print("\nResultado: %s" % ("aprovado" if falhas == 0 else "%s conferência(s) pendente(s)" % falhas))
    return 0 if falhas == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
