#!/usr/bin/env python3
"""Etapa 3: valida o provedor, publica a Edge Function e faz smoke test."""
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _comum import ask, cfg_get, http_json, load_config, save_config, supabase_rest, suporte_cfg


def _timeout(name, default):
    try:
        value = int(os.environ.get(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


CLI_TIMEOUT = _timeout("ZX_SUPORTE_CLI_TIMEOUT", 600)
AI_TIMEOUT = _timeout("ZX_SUPORTE_AI_TIMEOUT", 30)


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
    saida = " ".join(((proc.stdout or "") + (proc.stderr or "")).split())
    return proc.returncode == 0, saida[-800:], time.monotonic() - inicio


def _modelos_gemini(chave):
    status, body = http_json(
        "GET",
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": chave},
        timeout=AI_TIMEOUT,
    )
    if status != 200 or not isinstance(body, dict):
        return [], "Gemini não respondeu à listagem de modelos (HTTP %s)" % status
    nomes = []
    for item in body.get("models", []):
        if not isinstance(item, dict) or "generateContent" not in item.get("supportedGenerationMethods", []):
            continue
        nome = str(item.get("name", "")).removeprefix("models/")
        if nome:
            nomes.append(nome)
    return nomes, ""


def _escolher_modelos(nomes):
    # Aliases "-latest" seguem o modelo vigente e respondem mesmo quando a chave
    # não tem acesso aos nomes versionados (que o /models lista, mas devolvem 404).
    if "gemini-flash-lite-latest" in nomes and "gemini-flash-latest" in nomes:
        return "gemini-flash-lite-latest", "gemini-flash-latest"

    def chave_modelo(nome):
        partes = []
        for parte in nome.replace("-", ".").split("."):
            partes.append((0, int(parte)) if parte.isdigit() else (1, parte))
        return partes

    ordenados = sorted(set(nomes), key=chave_modelo, reverse=True)
    lite = next((nome for nome in ordenados if "flash-lite" in nome or "flash_lite" in nome), None)
    forte = next((nome for nome in ordenados if ("flash" in nome or "pro" in nome) and "lite" not in nome), None)
    return lite or "gemini-flash-lite-latest", forte or "gemini-flash-latest"


def _validar_gemini(chave, modelo):
    status, body = http_json(
        "POST",
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % modelo,
        headers={"x-goog-api-key": chave},
        corpo={
            "contents": [{"parts": [{"text": 'Responda somente JSON: {"ok":true}'}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=AI_TIMEOUT,
    )
    return status == 200 and isinstance(body, dict) and bool(body.get("candidates")), status


def _validar_anthropic(chave, modelo):
    status, body = http_json(
        "POST",
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": chave, "anthropic-version": "2023-06-01"},
        corpo={"model": modelo, "max_tokens": 20, "messages": [{"role": "user", "content": "Responda apenas OK."}]},
        timeout=AI_TIMEOUT,
    )
    return status == 200 and isinstance(body, dict) and bool(body.get("content")), status


def _env_file(valores):
    fd, nome = tempfile.mkstemp(prefix="zx-suporte-secrets-", suffix=".env")
    try:
        os.chmod(nome, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            for chave, valor in valores.items():
                if valor is not None and str(valor) != "":
                    arquivo.write("%s=%s\n" % (chave, str(valor).replace("\\", "\\\\").replace("\n", "")))
        return nome
    except BaseException:
        try:
            os.unlink(nome)
        except OSError:
            pass
        raise


def _secrets_set(cli, valores):
    caminho = _env_file(valores)
    try:
        ok, msg, elapsed = _run_long(cli + ["secrets", "set", "--env-file", caminho])
        print("%s secrets set em %.1fs" % ("✅" if ok else "❌", elapsed))
        if not ok and msg:
            print("  %s" % msg)
        return ok
    finally:
        try:
            os.unlink(caminho)
        except OSError:
            pass


def _deploy(cli):
    ok, msg, elapsed = _run_long(cli + ["functions", "deploy", "support-ai", "--no-verify-jwt"])
    print("%s deploy support-ai em %.1fs" % ("✅" if ok else "❌", elapsed))
    if not ok and msg:
        print("  %s" % msg)
    return ok


def _smoke(config, endpoint, origem):
    anon = cfg_get(config, "supabase_anon_key", "")
    headers = {"Content-Type": "application/json"}
    if anon:
        headers["apikey"] = anon
        headers["Authorization"] = "Bearer %s" % anon
    if origem:
        headers["Origin"] = origem
    ping_status, ping = http_json("POST", endpoint, headers=headers, corpo={"acao": "ping"}, timeout=AI_TIMEOUT)
    ping_ok = ping_status == 200 and isinstance(ping, dict) and ping.get("ok") is True
    print("%s smoke ping HTTP %s" % ("✅" if ping_ok else "❌", ping_status))
    conversa = "teste-setup-%s" % secrets.token_hex(6)
    msg_status, message = http_json(
        "POST", endpoint, headers=headers,
        corpo={"acao": "mensagem", "canal": "site", "conversa_id": conversa, "mensagem": "Teste automático da instalação."},
        timeout=AI_TIMEOUT,
    )
    persisted_status, persisted = supabase_rest(
        config,
        "GET",
        "/sup_mensagens?select=id&canal=eq.site&conversa_id=eq.%s&autor=eq.cliente&limit=1" % conversa,
        service=True,
    )
    persisted_ok = persisted_status == 200 and isinstance(persisted, list) and bool(persisted)
    ia_status, ia_rows = supabase_rest(
        config,
        "GET",
        "/sup_mensagens?select=id&canal=eq.site&conversa_id=eq.%s&autor=eq.ia&limit=1" % conversa,
        service=True,
    )
    ia_ok = ia_status == 200 and isinstance(ia_rows, list) and bool(ia_rows)
    contrato_ok = isinstance(message, dict) and all(key in message for key in ("resposta", "escalou", "ticket_id", "modelo"))
    if contrato_ok and message.get("escalou"):
        contrato_ok = bool(message.get("ticket_id"))
    elif contrato_ok:
        contrato_ok = bool(message.get("resposta")) and bool(message.get("modelo")) and ia_ok
    msg_ok = msg_status == 200 and contrato_ok and persisted_ok
    print("%s smoke mensagem HTTP %s" % ("✅" if msg_ok else "❌", msg_status))
    return ping_ok and msg_ok


def main():
    inicio = time.monotonic()
    config = load_config()
    suporte = suporte_cfg(config)
    base = str(cfg_get(config, "supabase_url", "")).rstrip("/")
    if not base:
        print("❌ Supabase URL ausente; conclua a Etapa 1 primeiro.")
        return 1
    cli = _cli()
    if not cli:
        print("❌ Supabase CLI/npx não encontrado.")
        return 1

    provedor = ask("Provedor (gemini/anthropic)", suporte.get("provedor", "gemini")).lower()
    if provedor not in ("gemini", "anthropic"):
        print("❌ Provedor inválido; use gemini ou anthropic.")
        return 1
    chave = ask("Chave da API do %s (não será exibida)" % provedor, secret=True)
    if provedor == "gemini":
        nomes, erro = _modelos_gemini(chave)
        if erro:
            print("❌ %s" % erro)
            return 1
        barato_sugerido, forte_sugerido = _escolher_modelos(nomes)
    else:
        barato_sugerido, forte_sugerido = "claude-haiku-4-5-20251001", "claude-sonnet-5"
    print("Modelos sugeridos: barato=%s; forte=%s" % (barato_sugerido, forte_sugerido))
    barato = ask("Modelo barato", suporte.get("modelo_barato", barato_sugerido))
    forte = ask("Modelo forte", suporte.get("modelo_forte", forte_sugerido))
    if provedor == "gemini":
        valido, status = _validar_gemini(chave, barato)
    else:
        valido, status = _validar_anthropic(chave, barato)
    if not valido:
        print("❌ A chave/modelo barato não foi validada (HTTP %s)." % status)
        return 1
    if provedor == "gemini":
        forte_valido, forte_status = _validar_gemini(chave, forte)
    else:
        forte_valido, forte_status = _validar_anthropic(chave, forte)
    if not forte_valido:
        print("❌ A chave/modelo forte não foi validada (HTTP %s)." % forte_status)
        return 1
    limiar = ask("Limiar de confiança", str(suporte.get("limiar_confianca", "0.7")))
    teto = ask("Teto diário de custo em USD", str(suporte.get("teto_diario_usd", "2.0")))
    try:
        if not 0 < float(limiar) <= 1 or float(teto) <= 0:
            raise ValueError()
    except ValueError:
        print("❌ Limiar deve estar entre 0 e 1 e teto deve ser positivo.")
        return 1

    origens = suporte.get("origens", "")
    valores = {
        "GEMINI_API_KEY": chave if provedor == "gemini" else "",
        "ANTHROPIC_API_KEY": chave if provedor == "anthropic" else "",
        "SUPORTE_ORIGENS": origens,
    }
    if not _secrets_set(cli, valores) or not _deploy(cli):
        return 1

    endpoint = base + "/functions/v1/support-ai"
    suporte.update({"provedor": provedor, "modelo_barato": barato, "modelo_forte": forte, "limiar_confianca": float(limiar), "teto_diario_usd": float(teto)})
    save_config(config)
    if not _smoke(config, endpoint, str(origens).split(",")[0].strip() if origens else ""):
        print("❌ A Edge Function foi publicada, mas o smoke não foi confirmado.")
        return 1
    print("\nEtapa 3 concluída em %.2fs." % (time.monotonic() - inicio))
    return 0


if __name__ == "__main__":
    sys.exit(main())
