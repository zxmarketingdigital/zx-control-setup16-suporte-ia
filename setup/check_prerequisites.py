#!/usr/bin/env python3
"""Etapa 0: confere o ambiente local antes de instalar o Setup 16."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _comum import CONFIG_PATH, cfg_get, load_config


def _timeout(name, default):
    try:
        value = int(os.environ.get(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


COMMAND_TIMEOUT = _timeout("ZX_SUPORTE_PREREQ_TIMEOUT", 30)


def _run(command):
    """Retorna (ok, saída curta), sem vazar argumentos ou credenciais."""
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    saida = ((process.stdout or "") + (process.stderr or "")).strip()
    return process.returncode == 0, " ".join(saida.split())[:160]


def _comando_versao(candidatos):
    for comando in candidatos:
        if not shutil.which(comando[0]):
            continue
        ok, saida = _run(comando)
        if ok:
            return True, "%s: %s" % (comando[0], saida or "disponível")
    return False, "não encontrado ou não respondeu"


def _linha(status, nome, detalhe, instrucao):
    simbolo = {"ok": "✅", "warn": "⚠️", "fail": "❌"}[status]
    print("%-3s %-24s %s" % (simbolo, nome, detalhe))
    if status != "ok":
        print("    Resolva: %s" % instrucao)


def main():
    inicio = time.monotonic()
    config = load_config()
    obrigatorias = []

    if sys.version_info >= (3, 9):
        _linha("ok", "Python", "%s.%s" % sys.version_info[:2], "")
    else:
        _linha("fail", "Python", "versão %s.%s" % sys.version_info[:2], "instale Python 3.9 ou mais recente")
        obrigatorias.append("Python")

    for nome, candidatos, instrucao in [
        ("git", [("git", "--version")], "instale o Git e tente novamente"),
        ("Node/npx", [("node", "--version"), ("npx", "--version")], "instale Node.js, que inclui o npx"),
        ("Supabase CLI", [("supabase", "--version"), ("npx", "supabase", "--version")], "instale o Supabase CLI ou deixe o npx disponível"),
        ("Wrangler", [("wrangler", "--version"), ("npx", "wrangler", "--version")], "instale Wrangler ou deixe o npx disponível"),
    ]:
        ok, detalhe = _comando_versao(candidatos)
        _linha("ok" if ok else "fail", nome, detalhe, instrucao)
        if not ok:
            obrigatorias.append(nome)

    if CONFIG_PATH.is_file():
        url = cfg_get(config, "supabase_url", "")
        anon = cfg_get(config, "supabase_anon_key", "")
        if url and anon:
            _linha("ok", "config Supabase", "URL e anon configurados", "")
        else:
            _linha("fail", "config Supabase", "arquivo existe, mas faltam supabase_url ou anon", "rode a configuração do Supabase e grave URL + anon em %s" % CONFIG_PATH)
            obrigatorias.append("config Supabase")
    else:
        _linha("fail", "config.json", "arquivo ausente", "execute o Setup anterior que cria %s" % CONFIG_PATH)
        obrigatorias.append("config.json")

    evolution = cfg_get(config, "evolution_url", "") and cfg_get(config, "evolution_api_key", "") and cfg_get(config, "evolution_instance", "")
    if evolution:
        _linha("ok", "Evolution", "configurada; canal WhatsApp disponível", "")
    else:
        _linha("warn", "Evolution", "não configurada; somente o canal site funcionará", "configure evolution_url, evolution_api_key e evolution_instance quando quiser WhatsApp")

    if cfg_get(config, "resend_api_key", ""):
        _linha("ok", "Resend", "configurado; auditoria poderá enviar e-mail", "")
    else:
        _linha("warn", "Resend", "não configurado; auditoria não enviará e-mail", "grave resend_api_key no config.json quando quiser habilitar e-mail")

    elapsed = time.monotonic() - inicio
    print("\nEtapa 0 concluída em %.2fs." % elapsed)
    if obrigatorias:
        print("Faltam requisitos obrigatórios: %s." % ", ".join(obrigatorias))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
