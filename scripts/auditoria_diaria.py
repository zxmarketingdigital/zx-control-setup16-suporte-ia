#!/usr/bin/env python3
"""Gera e, quando autorizado, envia a auditoria diária do suporte."""
import argparse
import html
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
from _comum import HTTP_TIMEOUT, SUPORTE_DIR, cfg_get, http_json, load_config, supabase_rest

DEFAULT_TIMEOUT = 600


def _iso_agora():
    return datetime.now(timezone.utc)


def _buscar(config, caminho):
    status, dados = supabase_rest(config, "GET", caminho)
    if status < 200 or status >= 300:
        raise RuntimeError("HTTP %s em %s: %s" % (status, caminho, str(dados)[:300]))
    return dados if isinstance(dados, list) else []


def _filtro_data(campo, inicio):
    return "%s=gte.%s" % (campo, quote(inicio.isoformat(), safe=""))


def coletar(config, dias):
    agora = _iso_agora()
    inicio = agora - timedelta(days=dias)
    mensagens = _buscar(config, "/sup_mensagens?select=canal,conversa_id,autor,created_at,modelo&%s&limit=10000" % _filtro_data("created_at", inicio))
    tickets = _buscar(config, "/sup_tickets?select=status,created_at,updated_at,resolvido_em,conversa_id,canal&%s&limit=10000" % _filtro_data("created_at", inicio))
    tickets_abertos_lista = _buscar(config, "/sup_tickets?select=status,created_at,updated_at,resolvido_em,conversa_id,canal&status=neq.resolvido&limit=10000")
    uso = _buscar(config, "/sup_uso_ia?select=etapa,custo_usd,erro,created_at&%s&limit=10000" % _filtro_data("created_at", inicio))
    candidatas = _buscar(config, "/sup_kb_candidatas?select=pergunta,ocorrencias,status,created_at&status=eq.pendente&order=ocorrencias.desc&limit=5")
    config_rows = _buscar(config, "/sup_config?select=chave,valor&limit=1000")
    conversas = {(item.get("canal"), item.get("conversa_id")) for item in mensagens if item.get("conversa_id")}
    ia = [item for item in mensagens if item.get("autor") == "ia"]
    clientes = [item for item in mensagens if item.get("autor") == "cliente"]
    conversas_cliente = {(item.get("canal"), item.get("conversa_id")) for item in clientes if item.get("conversa_id")}
    conversas_ia = {(item.get("canal"), item.get("conversa_id")) for item in ia if item.get("conversa_id")}
    conversas_com_ticket = {(item.get("canal"), item.get("conversa_id")) for item in tickets_abertos_lista}
    resolvidas_ia = (conversas_cliente & conversas_ia) - conversas_com_ticket
    novos = len(tickets)
    resolvidos = len([item for item in tickets if item.get("status") == "resolvido" or item.get("resolvido_em")])
    abertos = len(tickets_abertos_lista)
    limite_backlog = agora - timedelta(hours=24)
    backlog = []
    for item in tickets_abertos_lista:
        if str(item.get("created_at", "")) < limite_backlog.isoformat():
            backlog.append(item)
    custo = 0.0
    fortes = 0
    erros = 0
    for item in uso:
        try:
            custo += float(item.get("custo_usd") or 0)
        except (TypeError, ValueError):
            pass
        if item.get("etapa") == "forte":
            fortes += 1
        if item.get("erro"):
            erros += 1
    teto = 0.0
    por_chave = {str(item.get("chave")): item.get("valor") for item in config_rows}
    suporte = config.get("suporte") if isinstance(config.get("suporte"), dict) else {}
    try:
        teto = float(por_chave.get("teto_diario_usd") or suporte.get("teto_diario_usd") or 0)
    except (TypeError, ValueError):
        pass
    return {
        "inicio": inicio.isoformat(),
        "fim": agora.isoformat(),
        "dias": dias,
        "conversas": len(conversas),
        "mensagens": len(mensagens),
        "mensagens_cliente": len(clientes),
        "mensagens_ia": len(ia),
        "resolucao_ia": (100.0 * len(resolvidas_ia) / len(conversas_cliente)) if conversas_cliente else 0.0,
        "tickets_novos": novos,
        "tickets_abertos": abertos,
        "tickets_resolvidos": resolvidos,
        "backlog_24h": len(backlog),
        "custo_usd": custo,
        "teto_usd": teto,
        "percentual_teto": (100.0 * custo / teto) if teto > 0 else None,
        "fortes": fortes,
        "percentual_forte": (100.0 * fortes / len(uso)) if uso else 0.0,
        "erros_ia": erros,
        "candidatas": candidatas,
    }


def _linha(nome, valor):
    return "<tr><th>%s</th><td>%s</td></tr>" % (html.escape(nome), html.escape(str(valor)))


def gerar_html(metricas):
    teto = "não configurado" if metricas["percentual_teto"] is None else "%.2f%%" % metricas["percentual_teto"]
    linhas = [
        _linha("Janela", "%s até %s" % (metricas["inicio"], metricas["fim"])),
        _linha("Conversas", metricas["conversas"]),
        _linha("Mensagens", metricas["mensagens"]),
        _linha("Resolvida pela IA", "%.2f%%" % metricas["resolucao_ia"]),
        _linha("Tickets novos", metricas["tickets_novos"]),
        _linha("Tickets abertos", metricas["tickets_abertos"]),
        _linha("Tickets resolvidos", metricas["tickets_resolvidos"]),
        _linha("Backlog acima de 24h", metricas["backlog_24h"]),
        _linha("Custo em USD", "%.6f" % metricas["custo_usd"]),
        _linha("Percentual do teto", teto),
        _linha("Uso do modelo forte", "%.2f%%" % metricas["percentual_forte"]),
        _linha("Erros de IA", metricas["erros_ia"]),
    ]
    itens = "".join(
        "<li>%s (%s ocorrências)</li>" % (html.escape(str(item.get("pergunta", ""))), html.escape(str(item.get("ocorrencias", 0))))
        for item in metricas["candidatas"]
    ) or "<li>Nenhuma candidata pendente na consulta.</li>"
    return "<!doctype html><html lang=\"pt-BR\"><meta charset=\"utf-8\"><title>Auditoria do suporte</title><style>body{font:16px sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}table{border-collapse:collapse;width:100%%}th,td{border:1px solid #ddd;padding:.55rem;text-align:left}th{background:#f5f5f5}</style><h1>Auditoria diária do suporte</h1><table>%s</table><h2>Candidatas pendentes</h2><ul>%s</ul></html>" % ("".join(linhas), itens)


def resumo(metricas):
    return "Auditoria: %s conversas, %s mensagens, %s tickets abertos, %s tickets resolvidos, custo USD %.6f, %s erros de IA." % (
        metricas["conversas"], metricas["mensagens"], metricas["tickets_abertos"], metricas["tickets_resolvidos"], metricas["custo_usd"], metricas["erros_ia"]
    )


def gravar_relatorio(conteudo):
    pasta = SUPORTE_DIR / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = "auditoria-%s.html" % datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = pasta / nome
    temporario = destino.with_suffix(".tmp")
    temporario.write_text(conteudo, encoding="utf-8")
    temporario.replace(destino)
    if not destino.is_file() or destino.stat().st_size == 0:
        raise RuntimeError("relatório local não foi conferido")
    return destino


def enviar(config, conteudo):
    chave = cfg_get(config, "resend_api_key", "")
    destino = cfg_get(config, "email_aluno", "")
    remetente = cfg_get(config, "email_from", "onboarding@resend.dev")
    if not chave or not destino:
        raise RuntimeError("Resend ou email_aluno não configurado")
    status, resposta = http_json(
        "POST",
        "https://api.resend.com/emails",
        headers={"Authorization": "Bearer " + str(chave)},
        corpo={"from": remetente, "to": [destino], "subject": "Auditoria diária do suporte", "html": conteudo},
        timeout=HTTP_TIMEOUT,
    )
    if status < 200 or status >= 300 or not isinstance(resposta, dict) or not resposta.get("id"):
        raise RuntimeError("Resend não confirmou o envio: HTTP %s" % status)
    return resposta.get("id")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gera a auditoria diária do suporte.")
    parser.add_argument("--dias", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="gera e confere, sem enviar")
    parser.add_argument("--sem-email", action="store_true", help="imprime e não envia")
    args = parser.parse_args(argv)
    if args.dias < 1:
        parser.error("--dias deve ser maior que zero")
    inicio = time.monotonic()
    bloqueado = bool(args.dry_run or args.sem_email)
    try:
        config = load_config()
        metricas = coletar(config, args.dias)
        conteudo = gerar_html(metricas)
        caminho = gravar_relatorio(conteudo)
        print(resumo(metricas))
        print("Relatório local conferido: %s" % caminho)
        if bloqueado:
            print("Envio bloqueado por %s." % ("--dry-run" if args.dry_run else "--sem-email"))
        else:
            identificador = enviar(config, conteudo)
            print("E-mail confirmado pelo Resend: %s" % identificador)
        print("Tempo decorrido: %.2fs" % (time.monotonic() - inicio))
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        print("Auditoria não concluída: %s" % exc, file=sys.stderr)
        print("Tempo decorrido: %.2fs" % (time.monotonic() - inicio), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
