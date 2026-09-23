#!/usr/bin/env python3
"""Rotina diária de suporte do Setup 16 — coleta, grava resposta aprovada e ensina a KB.

Só biblioteca padrão, compatível com Python 3.9 (nada de `str | None`). Segue as
mesmas convenções de scripts/auditoria_diaria.py e scripts/kb_importar.py: toda
leitura de config passa por _comum.cfg_get/supabase_rest, e toda escrita confere
o efeito lendo de volta antes de sair com código 0.

Este script NÃO decide o texto da resposta nem aprova nada sozinho — quem julga é
o Claude, na conversa com o aluno, seguindo a skill skills/suporte-rotina-diaria/.
O script só coleta dados e grava o que já foi aprovado.

Subcomandos:
  coletar [--dias N]                                    imprime JSON na saída padrão
  responder --ticket <id> --texto-arquivo <path> [--resolver]
  aprovar-kb --candidata <id> [--pergunta ...] --resposta-arquivo <path> [--tema ...] [--fonte ...]
  descartar-kb --candidata <id>
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
sys.path.insert(0, str(ROOT / "scripts"))
from _comum import load_config, supabase_rest  # noqa: E402

# Reaproveita a mesma conta de métricas da Etapa 6 em vez de duplicar a lógica —
# scripts/auditoria_diaria.py não é alterado por este arquivo, só importado.
from auditoria_diaria import coletar as coletar_metricas  # noqa: E402

# Reaproveita a mesma normalização de pergunta usada na importação da KB (Etapa 2/5),
# pra não duplicar critério de duplicata entre os dois scripts.
from kb_importar import normalizar as normalizar_pergunta  # noqa: E402

PRIORIDADE_PESO = {"alta": 0, "normal": 1, "baixa": 2}
LIMITE_TICKETS_ABERTOS = 200
LIMITE_MENSAGENS_POR_TICKET = 500
LIMITE_CANDIDATAS = 100
LIMITE_MENSAGENS_JANELA = 5000
TEMA_PADRAO = "Perguntas recorrentes"
FONTE_PADRAO = "base que aprende"


def _buscar(config, caminho):
    # type: (dict, str) -> list
    status, dados = supabase_rest(config, "GET", caminho)
    if status < 200 or status >= 300:
        raise SystemExit("HTTP %s ao ler %s: %s" % (status, caminho, str(dados)[:400]))
    return dados if isinstance(dados, list) else []


def _rpc(config, nome, args):
    # type: (dict, str, dict) -> list
    status, dados = supabase_rest(config, "POST", "/rpc/%s" % nome, args)
    if status < 200 or status >= 300:
        # Busca de KB relacionada é apoio, não bloqueia a coleta — registra e segue vazio.
        print("aviso: RPC %s falhou (HTTP %s): %s" % (nome, status, str(dados)[:200]), file=sys.stderr)
        return []
    return dados if isinstance(dados, list) else []


def _ler_texto(caminho, rotulo):
    # type: (str, str) -> str
    alvo = Path(caminho).expanduser()
    if not alvo.is_file():
        raise SystemExit("%s não encontrado: %s" % (rotulo, alvo))
    texto = alvo.read_text(encoding="utf-8").strip()
    if not texto:
        raise SystemExit("%s está vazio: %s" % (rotulo, alvo))
    return texto


def _kb_relacionada(config, ticket, mensagens):
    consulta = str(ticket.get("assunto") or "")
    mensagens_cliente = [m.get("conteudo") for m in mensagens if m.get("autor") == "cliente" and m.get("conteudo")]
    if mensagens_cliente:
        consulta = (consulta + " " + str(mensagens_cliente[-1])).strip()
    if not consulta.strip():
        return []
    return _rpc(config, "sup_buscar_kb", {"consulta": consulta, "limite": 5})


def _conversas_ia_periodo(config, inicio_iso):
    filtro = "created_at=gte.%s" % quote(inicio_iso, safe="")
    mensagens = _buscar(
        config,
        "/sup_mensagens?select=canal,conversa_id,autor,conteudo,confianca,ticket_id,created_at&%s"
        "&order=created_at.asc&limit=%s" % (filtro, LIMITE_MENSAGENS_JANELA),
    )
    agrupado = {}
    for m in mensagens:
        conversa_id = m.get("conversa_id")
        if not conversa_id:
            continue
        chave = (m.get("canal"), conversa_id)
        info = agrupado.setdefault(chave, {
            "canal": chave[0], "conversa_id": chave[1], "mensagens_ia": 0,
            "confiancas": [], "ultima_pergunta_cliente": None, "ultima_resposta_ia": None,
            "ticket_id": None,
        })
        if m.get("autor") == "ia":
            info["mensagens_ia"] += 1
            info["ultima_resposta_ia"] = m.get("conteudo")
            if m.get("confianca") is not None:
                try:
                    info["confiancas"].append(float(m["confianca"]))
                except (TypeError, ValueError):
                    pass
        elif m.get("autor") == "cliente":
            info["ultima_pergunta_cliente"] = m.get("conteudo")
        if m.get("ticket_id"):
            info["ticket_id"] = m.get("ticket_id")
    resultado = []
    for info in agrupado.values():
        if info["mensagens_ia"] == 0:
            continue
        confs = info.pop("confiancas")
        info["confianca_media"] = round(sum(confs) / len(confs), 3) if confs else None
        info["escalada"] = bool(info["ticket_id"])
        resultado.append(info)
    # Prioriza pra leitura: não escaladas primeiro (potencial gap silencioso de KB),
    # depois pela menor confiança média — é onde a resposta da IA mais tremeu.
    resultado.sort(key=lambda item: (item["escalada"], item["confianca_media"] if item["confianca_media"] is not None else 1.0))
    return resultado


def coletar(config, dias):
    metricas = coletar_metricas(config, dias)
    abertos = _buscar(
        config,
        "/sup_tickets?select=id,numero,canal,conversa_id,contato_nome,contato_whatsapp,contato_email,"
        "assunto,status,prioridade,motivo_escalonamento,sugestao_ia,atribuido_a,created_at,updated_at"
        "&status=neq.resolvido&order=created_at.asc&limit=%s" % LIMITE_TICKETS_ABERTOS,
    )
    tickets = []
    for ticket in abertos:
        mensagens = _buscar(
            config,
            "/sup_mensagens?select=autor,conteudo,modelo,confianca,created_at&ticket_id=eq.%s"
            "&order=created_at.asc&limit=%s" % (ticket["id"], LIMITE_MENSAGENS_POR_TICKET),
        )
        ticket = dict(ticket)
        ticket["mensagens"] = mensagens
        ticket["kb_relacionada"] = _kb_relacionada(config, ticket, mensagens)
        tickets.append(ticket)
    tickets.sort(key=lambda t: (PRIORIDADE_PESO.get(t.get("prioridade"), 1), t.get("created_at") or ""))
    candidatas = _buscar(
        config,
        "/sup_kb_candidatas?select=id,pergunta,contexto,resposta_sugerida,ocorrencias,ticket_id,created_at,updated_at"
        "&status=eq.pendente&order=ocorrencias.desc,created_at.asc&limit=%s" % LIMITE_CANDIDATAS,
    )
    conversas_ia = _conversas_ia_periodo(config, metricas["inicio"])
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "dias": dias,
        "janela": {"inicio": metricas["inicio"], "fim": metricas["fim"]},
        "metricas": metricas,
        "tickets_abertos": tickets,
        "candidatas_kb_pendentes": candidatas,
        "conversas_ia_periodo": conversas_ia,
    }


def responder(config, ticket_id, texto, resolver):
    tickets = _buscar(
        config,
        "/sup_tickets?select=id,canal,conversa_id,numero,status,contato_whatsapp,contato_email"
        "&id=eq.%s" % ticket_id,
    )
    if not tickets:
        raise SystemExit("ticket não encontrado: %s" % ticket_id)
    ticket = tickets[0]
    if ticket.get("status") == "resolvido":
        raise SystemExit("ticket %s já está resolvido; use aprovar-kb/reabra no hub se precisar reabrir" % ticket_id)
    # Repetir o comando depois de uma falha no PATCH do status não duplica a resposta:
    # se a última mensagem humana do ticket já é este texto, reaproveita em vez de inserir.
    ultima = _buscar(config, "/sup_mensagens?select=id,conteudo&ticket_id=eq.%s&autor=eq.humano&order=created_at.desc&limit=1" % ticket_id)
    if ultima and (ultima[0].get("conteudo") or "").strip() == texto:
        mensagem_id = ultima[0]["id"]
    else:
        status, dados = supabase_rest(config, "POST", "/sup_mensagens", {
            "canal": ticket["canal"], "conversa_id": ticket["conversa_id"], "ticket_id": ticket_id,
            "autor": "humano", "conteudo": texto,
        })
        if status not in (200, 201) or not isinstance(dados, list) or not dados or not dados[0].get("id"):
            raise SystemExit("mensagem não foi gravada em sup_mensagens (HTTP %s): %s" % (status, str(dados)[:300]))
        mensagem_id = dados[0]["id"]
    novo_status = "resolvido" if resolver else "aguardando_cliente"
    patch = {"status": novo_status}
    if resolver:
        patch["resolvido_em"] = datetime.now(timezone.utc).isoformat()
    status2, dados2 = supabase_rest(config, "PATCH", "/sup_tickets?id=eq.%s" % ticket_id, patch)
    if status2 not in (200, 201):
        raise SystemExit("status do ticket não foi atualizado (HTTP %s): %s" % (status2, str(dados2)[:300]))
    conferido = _buscar(config, "/sup_tickets?select=id,status&id=eq.%s" % ticket_id)
    if not conferido or conferido[0].get("status") != novo_status:
        raise SystemExit("conferência falhou: o status gravado não bate com %r" % novo_status)
    link_whatsapp = None
    contato_whatsapp = ticket.get("contato_whatsapp")
    if contato_whatsapp:
        numero = "".join(char for char in str(contato_whatsapp) if char.isdigit())
        if numero:
            link_whatsapp = "https://wa.me/%s?text=%s" % (numero, quote(texto))
    resultado = {
        "ok": True, "ticket_id": ticket_id, "numero": ticket.get("numero"), "mensagem_id": mensagem_id,
        "status_ticket": novo_status, "texto": texto, "contato_whatsapp": contato_whatsapp,
        "whatsapp_link": link_whatsapp, "contato_email": ticket.get("contato_email"),
    }
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


def aprovar_kb(config, candidata_id, pergunta_override, resposta, tema, fonte):
    candidatas = _buscar(config, "/sup_kb_candidatas?select=*&id=eq.%s" % candidata_id)
    if not candidatas:
        raise SystemExit("candidata não encontrada: %s" % candidata_id)
    candidata = candidatas[0]
    if candidata.get("status") != "pendente":
        raise SystemExit("candidata %s não está pendente (status atual: %s)" % (candidata_id, candidata.get("status")))
    pergunta = (pergunta_override or candidata.get("pergunta") or "").strip()
    if not pergunta:
        raise SystemExit("pergunta final está vazia")
    chave = normalizar_pergunta(pergunta)
    existentes = _buscar(config, "/sup_kb?select=id,pergunta&limit=2000")
    existente_id = None
    for item in existentes:
        if normalizar_pergunta(item.get("pergunta")) == chave:
            existente_id = item.get("id")
            break
    corpo = {"tema": tema or TEMA_PADRAO, "pergunta": pergunta, "resposta": resposta, "fonte": fonte or FONTE_PADRAO, "ativo": True}
    if existente_id:
        status, dados = supabase_rest(config, "PATCH", "/sup_kb?id=eq.%s" % existente_id, corpo)
        kb_id = existente_id
    else:
        status, dados = supabase_rest(config, "POST", "/sup_kb", corpo)
        kb_id = dados[0]["id"] if isinstance(dados, list) and dados and dados[0].get("id") else None
    if status not in (200, 201) or not kb_id:
        raise SystemExit("gravação em sup_kb não confirmada (HTTP %s): %s" % (status, str(dados)[:300]))
    status2, dados2 = supabase_rest(config, "PATCH", "/sup_kb_candidatas?id=eq.%s" % candidata_id, {
        "status": "aprovada", "resposta_sugerida": resposta,
    })
    if status2 not in (200, 201):
        raise SystemExit("candidata não foi marcada como aprovada (HTTP %s): %s" % (status2, str(dados2)[:300]))
    conferido_kb = _buscar(config, "/sup_kb?select=id,pergunta,ativo&id=eq.%s" % kb_id)
    conferido_cand = _buscar(config, "/sup_kb_candidatas?select=id,status&id=eq.%s" % candidata_id)
    if not conferido_kb or not conferido_kb[0].get("ativo"):
        raise SystemExit("conferência falhou: item %s não está ativo em sup_kb" % kb_id)
    if not conferido_cand or conferido_cand[0].get("status") != "aprovada":
        raise SystemExit("conferência falhou: candidata %s não ficou com status aprovada" % candidata_id)
    print(json.dumps({
        "ok": True, "kb_id": kb_id, "candidata_id": candidata_id, "pergunta": pergunta,
        "atualizado_existente": bool(existente_id),
    }, ensure_ascii=False, indent=2))


def descartar_kb(config, candidata_id):
    candidatas = _buscar(config, "/sup_kb_candidatas?select=id,status&id=eq.%s" % candidata_id)
    if not candidatas:
        raise SystemExit("candidata não encontrada: %s" % candidata_id)
    if candidatas[0].get("status") != "pendente":
        raise SystemExit("candidata %s não está pendente (status atual: %s)" % (candidata_id, candidatas[0].get("status")))
    status, dados = supabase_rest(config, "PATCH", "/sup_kb_candidatas?id=eq.%s" % candidata_id, {"status": "rejeitada"})
    if status not in (200, 201):
        raise SystemExit("candidata não foi marcada como rejeitada (HTTP %s): %s" % (status, str(dados)[:300]))
    conferido = _buscar(config, "/sup_kb_candidatas?select=id,status&id=eq.%s" % candidata_id)
    if not conferido or conferido[0].get("status") != "rejeitada":
        raise SystemExit("conferência falhou: candidata %s não ficou com status rejeitada" % candidata_id)
    print(json.dumps({"ok": True, "candidata_id": candidata_id, "status": "rejeitada"}, ensure_ascii=False, indent=2))


def _parser():
    parser = argparse.ArgumentParser(description="Rotina diária de suporte: coleta, resposta aprovada e KB que aprende.")
    sub = parser.add_subparsers(dest="comando")

    p_coletar = sub.add_parser("coletar", help="tickets abertos com conversa completa, conversas da IA, candidatas e métricas do período")
    p_coletar.add_argument("--dias", type=int, default=1)

    p_responder = sub.add_parser("responder", help="grava no ticket a resposta já aprovada pelo aluno")
    p_responder.add_argument("--ticket", required=True, help="id (uuid) do ticket")
    p_responder.add_argument("--texto-arquivo", required=True, help="arquivo com o texto final da resposta")
    p_responder.add_argument("--resolver", action="store_true", help="fecha o ticket em vez de aguardar_cliente")

    p_aprovar = sub.add_parser("aprovar-kb", help="grava a Q&A aprovada em sup_kb e marca a candidata")
    p_aprovar.add_argument("--candidata", required=True, help="id (uuid) da candidata em sup_kb_candidatas")
    p_aprovar.add_argument("--pergunta", default="", help="pergunta final (default: a da própria candidata)")
    p_aprovar.add_argument("--resposta-arquivo", required=True, help="arquivo com a resposta final confirmada pelo aluno")
    p_aprovar.add_argument("--tema", default=TEMA_PADRAO)
    p_aprovar.add_argument("--fonte", default=FONTE_PADRAO)

    p_descartar = sub.add_parser("descartar-kb", help="marca a candidata como rejeitada, sem gravar nada em sup_kb")
    p_descartar.add_argument("--candidata", required=True)

    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.comando:
        parser.print_help()
        return 2
    inicio = time.monotonic()
    config = load_config()
    try:
        if args.comando == "coletar":
            if args.dias < 1:
                parser.error("--dias deve ser maior que zero")
            resultado = coletar(config, args.dias)
            print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
        elif args.comando == "responder":
            texto = _ler_texto(args.texto_arquivo, "arquivo de resposta")
            responder(config, args.ticket, texto, args.resolver)
        elif args.comando == "aprovar-kb":
            resposta = _ler_texto(args.resposta_arquivo, "arquivo de resposta da KB")
            aprovar_kb(config, args.candidata, args.pergunta, resposta, args.tema, args.fonte)
        elif args.comando == "descartar-kb":
            descartar_kb(config, args.candidata)
        else:
            parser.error("comando desconhecido: %s" % args.comando)
    except (RuntimeError, OSError, ValueError) as exc:
        print("rotina_suporte: %s" % exc, file=sys.stderr)
        print("Tempo decorrido: %.2fs" % (time.monotonic() - inicio), file=sys.stderr)
        return 1
    print("Tempo decorrido: %.2fs" % (time.monotonic() - inicio), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
