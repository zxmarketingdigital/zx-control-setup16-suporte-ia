#!/usr/bin/env python3
"""Etapa 0: confere o ambiente local antes de instalar o Setup 16.

Não exige nenhum setup anterior: cria o config.json mínimo se não existir e
reaproveita o que já estiver válido. As credenciais do Supabase que faltarem
são coletadas na Etapa 1."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _comum import CONFIG_PATH, ConfigBackupError, cfg_get, ensure_config


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

    try:
        config, nota = ensure_config()
        _linha("ok", "config.json", nota, "")
    except ConfigBackupError:
        # backup do config corrompido falhou: mensagem ja impressa, original intacto. Nao segue como concluida.
        _linha("fail", "config.json", "não consegui guardar a cópia de segurança do config.json inválido", "verifique a permissão da pasta %s e rode de novo" % CONFIG_PATH.parent)
        print("\nEtapa 0 NÃO concluída: o config.json original foi preservado.")
        return 1
    except OSError as exc:
        _linha("fail", "config.json", "não consegui preparar %s (%s)" % (CONFIG_PATH, exc), "verifique a permissão da pasta %s e rode de novo" % CONFIG_PATH.parent)
        print("\nEtapa 0 NÃO concluída: o config.json não foi preparado.")
        return 1

    url = cfg_get(config, "supabase_url", "")
    anon = cfg_get(config, "supabase_anon_key", "")
    if url and anon:
        _linha("ok", "config Supabase", "URL e anon configurados", "")
    else:
        _linha("warn", "config Supabase", "ainda não configurado; a Etapa 1 pede URL, anon key e service role key do seu projeto", "se ainda não tem projeto, crie um grátis em supabase.com (New project) e copie as chaves em Project Settings > API")

    if cfg_get(config, "resend_api_key", ""):
        _linha("ok", "Resend", "configurado; auditoria poderá enviar e-mail", "")
    else:
        _linha("warn", "Resend", "não configurado; auditoria não enviará e-mail", "grave resend_api_key e email_aluno no config.json quando quiser habilitar e-mail (opcional)")

    elapsed = time.monotonic() - inicio
    print("\nEtapa 0 concluída em %.2fs." % elapsed)
    if obrigatorias:
        print("Faltam requisitos obrigatórios: %s." % ", ".join(obrigatorias))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
