#!/usr/bin/env python3
"""Etapa 1: cria a fundação do suporte no Supabase do aluno."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _comum import (
    REPO_ROOT,
    ask,
    cfg_get,
    load_config,
    save_config,
    supabase_rest,
    suporte_cfg,
)


def _timeout(name, default):
    try:
        value = int(os.environ.get(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


CLI_TIMEOUT = _timeout("ZX_SUPORTE_CLI_TIMEOUT", 600)
TABLES = [
    ("sup_config", "chave"),
    ("sup_equipe", "user_id"),
    ("sup_tickets", "id"),
    ("sup_mensagens", "id"),
    ("sup_kb", "id"),
    ("sup_kb_candidatas", "id"),
    ("sup_uso_ia", "id"),
]
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20260922000001_suporte.sql"


def _cli():
    if shutil.which("supabase"):
        return ["supabase"]
    if shutil.which("npx"):
        return ["npx", "supabase"]
    return None


def _run_long(command):
    inicio = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=CLI_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc), time.monotonic() - inicio
    saida = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, " ".join(saida.split())[-800:], time.monotonic() - inicio


def _esperar_sql_editor():
    print("\n⚠️  O CLI não aplicou a migration.")
    print("Abra o SQL Editor do projeto no Supabase, cole o conteúdo de:")
    print("  %s" % MIGRATION)
    print("Execute todo o arquivo, aguarde a conclusão e volte para esta janela.")
    try:
        input("Pressione ENTER para continuar a conferência: ")
    except EOFError:
        pass


def _conferir_tabelas(config):
    falhas = []
    for tabela, coluna in TABLES:
        status, body = supabase_rest(config, "GET", "/%s?select=%s&limit=1" % (tabela, coluna), service=True)
        if status != 200 or not isinstance(body, list):
            falhas.append("%s (HTTP %s)" % (tabela, status))
        else:
            print("  ✅ %s responde via REST" % tabela)
    return falhas


def _configurar_negocio(config):
    status, rows = supabase_rest(config, "GET", "/sup_config?select=chave,valor", service=True)
    atuais = {}
    if status == 200 and isinstance(rows, list):
        atuais = {row.get("chave"): row.get("valor") for row in rows if isinstance(row, dict)}
    nome_atual = atuais.get("negocio_nome")
    descricao_atual = atuais.get("negocio_descricao")
    nome = ask("Nome do negócio", str(nome_atual) if nome_atual and nome_atual != "Seu negócio" else None)
    descricao = ask("Descrição curta do negócio", str(descricao_atual) if descricao_atual and descricao_atual != "Atendimento ao cliente" else None)
    whats_atual = atuais.get("whatsapp_atendimento")
    print("  O WhatsApp de atendimento aparece para o cliente quando a IA não sabe responder e abre um ticket")
    print("  (\"se preferir, fale direto com a gente no WhatsApp ...\"). Use o número do NEGÓCIO, nunca um pessoal.")
    whats = ask("WhatsApp de atendimento com DDI (ex.: 5511999999999) — Enter para não mostrar", str(whats_atual) if whats_atual else "")
    whats = "".join(ch for ch in whats if ch.isdigit())
    if len(whats) in (10, 11) and not whats.startswith("55"):
        whats = "55" + whats  # número brasileiro digitado sem DDI; o link wa.me exige o formato internacional
        print("  ℹ️  Acrescentei o DDI 55: %s" % whats)
    if whats and not 8 <= len(whats) <= 15:
        print("  ⚠️  Número inválido — deixei sem WhatsApp de atendimento. Rode esta etapa de novo para corrigir.")
        whats = ""
    corpo = [{"chave": "negocio_nome", "valor": nome}, {"chave": "negocio_descricao", "valor": descricao},
             {"chave": "whatsapp_atendimento", "valor": whats}]
    status, _ = supabase_rest(
        config,
        "POST",
        "/sup_config",
        corpo,
        service=True,
        extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"},
    )
    if status not in (200, 201):
        print("❌ Não consegui gravar nome e descrição do negócio (HTTP %s)." % status)
        return False
    status, rows = supabase_rest(config, "GET", "/sup_config?select=chave,valor", service=True)
    conferidos = {row.get("chave"): row.get("valor") for row in rows or [] if isinstance(row, dict)} if status == 200 else {}
    ok = (conferidos.get("negocio_nome") == nome and conferidos.get("negocio_descricao") == descricao
          and conferidos.get("whatsapp_atendimento", "") == whats)
    print("  ✅ Configuração do negócio conferida" if ok else "  ❌ Configuração do negócio não foi conferida")
    return ok


def main():
    inicio = time.monotonic()
    config = load_config()
    suporte = suporte_cfg(config)
    projeto = cfg_get(config, "supabase_project_id", "") or suporte.get("project_ref", "")
    projeto = ask("Project ref do Supabase", projeto or None)
    service_key = cfg_get(config, "supabase_service_role_key", "")
    if not service_key:
        service_key = ask("Service role key do Supabase (não será exibida)", secret=True)
    config["supabase_project_id"] = projeto
    config["supabase_service_role_key"] = service_key
    suporte["project_ref"] = projeto
    save_config(config)

    cli = _cli()
    cli_ok = False
    if cli:
        link_ok, link_msg, link_time = _run_long(cli + ["link", "--project-ref", projeto])
        print("%s link em %.1fs: %s" % ("✅" if link_ok else "⚠️", link_time, link_msg or "sem saída"))
        if link_ok:
            push_ok, push_msg, push_time = _run_long(cli + ["db", "push"])
            print("%s db push em %.1fs: %s" % ("✅" if push_ok else "⚠️", push_time, push_msg or "sem saída"))
            cli_ok = push_ok
        if not cli_ok:
            _esperar_sql_editor()
    else:
        print("⚠️  Supabase CLI/npx não encontrado; use o SQL Editor.")
        _esperar_sql_editor()

    falhas = _conferir_tabelas(config)
    if falhas:
        print("❌ Tabelas não conferidas: %s" % ", ".join(falhas))
        print("Migration esperada: %s" % MIGRATION)
        return 1
    if not _configurar_negocio(config):
        return 1
    print("\nEtapa 1 concluída em %.2fs." % (time.monotonic() - inicio))
    return 0


if __name__ == "__main__":
    sys.exit(main())
