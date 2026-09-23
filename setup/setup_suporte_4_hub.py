#!/usr/bin/env python3
"""Etapa 4 — publica o hub e cadastra a primeira equipe de suporte.

O script só usa a biblioteca padrão e as funções compartilhadas de _comum.py.
Ele pode ser executado novamente: usuários são localizados por e-mail e a equipe
é feita por upsert.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _comum import (  # noqa: E402
    REPO_ROOT,
    ask,
    aviso,
    cfg_get,
    erro,
    http_json,
    load_config,
    save_config,
    sair,
    suporte_cfg,
    supabase_rest,
)


def _positive_timeout(name, default):
    try:
        value = int(os.environ.get(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


DEPLOY_TIMEOUT = _positive_timeout("ZX_SUPORTE_DEPLOY_TIMEOUT", 600)
CLI_TIMEOUT = _positive_timeout("ZX_SUPORTE_CLI_TIMEOUT", 600)
HUB_TITLE = "Hub de Suporte"


def elapsed(start):
    return "%.1fs" % (time.monotonic() - start)


def auth_headers(service_key):
    return {"apikey": service_key, "Authorization": "Bearer " + service_key}


def auth_users(config, service_key):
    base = str(cfg_get(config, "supabase_url", "")).rstrip("/")
    status, body = http_json("GET", base + "/auth/v1/admin/users?per_page=1000&page=1", headers=auth_headers(service_key))
    if status != 200 or not isinstance(body, dict):
        return []
    users = body.get("users", [])
    return users if isinstance(users, list) else []


def find_user(users, email):
    wanted = email.strip().lower()
    for user in users:
        if isinstance(user, dict) and str(user.get("email", "")).lower() == wanted:
            return user
    return None


def ensure_user(config, service_key, email, nome, admin=False):
    users = auth_users(config, service_key)
    found = find_user(users, email)
    if found and found.get("id"):
        return str(found["id"]), False
    senha = ask("Senha do usuário " + email, secret=True)
    base = str(cfg_get(config, "supabase_url", "")).rstrip("/")
    payload = {"email": email, "password": senha, "email_confirm": True, "user_metadata": {"nome": nome}}
    status, body = http_json("POST", base + "/auth/v1/admin/users", headers=auth_headers(service_key), corpo=payload)
    if status not in (200, 201):
        # Uma execução concorrente ou uma execução anterior pode ter criado o e-mail.
        found = find_user(auth_users(config, service_key), email)
        if not found or not found.get("id"):
            raise RuntimeError("não consegui criar o usuário " + email + " (HTTP " + str(status) + ")")
        return str(found["id"]), False
    if not isinstance(body, dict) or not body.get("id"):
        found = find_user(auth_users(config, service_key), email)
        if not found or not found.get("id"):
            raise RuntimeError("a API criou o usuário, mas não devolveu um id conferível")
        return str(found["id"]), True
    return str(body["id"]), True


def upsert_member(config, user_id, nome, papel):
    status, body = supabase_rest(
        config,
        "POST",
        "/sup_equipe",
        [{"user_id": user_id, "nome": nome, "papel": papel}],
        service=True,
        extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"},
    )
    if status not in (200, 201):
        raise RuntimeError("não consegui salvar a equipe (HTTP " + str(status) + ")")
    if not isinstance(body, list) or not body:
        raise RuntimeError("a equipe não retornou registro para conferência")


def slugify(value):
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    return (slug or "negocio")[:50]


def command(name):
    found = shutil.which(name)
    if found:
        return [found]
    npx = shutil.which("npx")
    if npx:
        return [npx, name]
    return None


def run_cli(args, timeout):
    started = time.monotonic()
    try:
        result = subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "comando não encontrado", elapsed(started)
    except subprocess.TimeoutExpired:
        return 124, "tempo limite excedido", elapsed(started)
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    return result.returncode, output, elapsed(started)


def ensure_pages_project(wrangler, slug, config):
    status, output, spent = run_cli(wrangler + ["pages", "project", "create", slug], CLI_TIMEOUT)
    print("  wrangler pages project create: " + spent)
    if status == 0:
        return True
    lower = output.lower()
    if "already exists" in lower or "already exist" in lower or "já existe" in lower or "exists" in lower:
        suporte = suporte_cfg(config)
        if suporte.get("pages_project") == slug:
            aviso("o projeto Pages já existente foi previamente identificado para este suporte; vou reutilizá-lo")
            return True
        confirmation = ask("O projeto Pages já existe. Para reutilizá-lo sem sobrescrever outro site, digite REUTILIZAR", default="")
        if confirmation.strip().upper() == "REUTILIZAR":
            suporte["pages_project"] = slug
            save_config(config)
            aviso("reutilização confirmada explicitamente")
            return True
        erro("projeto existente não identificado; deploy interrompido para evitar sobrescrita")
        return False
    erro("não consegui criar o projeto Pages")
    if output:
        print("  " + output[-800:])
    return False


def publish(wrangler, slug):
    started = time.monotonic()
    status, output, spent = run_cli(wrangler + ["pages", "deploy", "hub", "--project-name", slug, "--branch", "main"], DEPLOY_TIMEOUT)
    print("  deploy do hub: " + spent)
    if status != 0:
        if output:
            print("  " + output[-1000:])
        return None
    urls = re.findall(r"https://[a-zA-Z0-9.-]+\.pages\.dev", output)
    return urls[-1].rstrip("/") if urls else "https://" + slug + ".pages.dev"


def write_runtime_config(config, business_name, cor):
    hub_dir = REPO_ROOT / "hub"
    hub_dir.mkdir(parents=True, exist_ok=True)
    public_config = {
        "supabaseUrl": cfg_get(config, "supabase_url", ""),
        "anonKey": cfg_get(config, "supabase_anon_key", ""),
        "negocioNome": business_name,
        "cor": cor,
    }
    content = "window.SUPORTE_CONFIG = Object.freeze(" + json.dumps(public_config, ensure_ascii=False) + ");\n"
    (hub_dir / "config.js").write_text(content, encoding="utf-8")


def copy_widget():
    source = REPO_ROOT / "widget" / "suporte-widget.js"
    target = REPO_ROOT / "hub" / "suporte-widget.js"
    if not source.is_file():
        raise RuntimeError("widget/suporte-widget.js não existe")
    shutil.copyfile(str(source), str(target))


def smoke_hub(url):
    status, body = http_json("GET", url)
    if status != 200:
        return False, "HTTP " + str(status)
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    if HUB_TITLE not in text:
        return False, "o HTML publicado não contém " + HUB_TITLE
    return True, "HTTP 200 e título conferidos"


def smoke_asset(url, markers):
    status, body = http_json("GET", url)
    if status != 200:
        return False, "HTTP " + str(status)
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    missing = [marker for marker in markers if marker not in text]
    if missing:
        return False, "asset sem os marcadores esperados: " + ", ".join(missing)
    return True, "HTTP 200 e conteúdo conferido"


def main():
    started = time.monotonic()
    print("Etapa 4 — publicação do Hub de Suporte")
    config = load_config()
    supabase_url = cfg_get(config, "supabase_url", "")
    service_key = cfg_get(config, "supabase_service_role_key", "")
    anon_key = cfg_get(config, "supabase_anon_key", "")
    if not supabase_url or not service_key or not anon_key:
        sair(1, "Supabase incompleto no config.json; conclua a Etapa 1 antes da Etapa 4.")
    suporte = suporte_cfg(config)
    default_name = suporte.get("negocio_nome") or config.get("negocio_nome") or "Seu negócio"
    business_name = ask("Nome do negócio", default=str(default_name))
    color = ask("Cor do hub em hexadecimal", default=str(suporte.get("cor") or "#7C3AED"))
    email = ask("E-mail do primeiro administrador").lower()
    admin_id, created = ensure_user(config, service_key, email, business_name, admin=True)
    upsert_member(config, admin_id, business_name, "admin")
    ok_label = "criado" if created else "já existia"
    print("  ✅ administrador " + ok_label + " e conferido na equipe")

    more = ask("Adicionar outros membros agora? (s/N)", default="N").lower()
    if more in ("s", "sim", "y", "yes"):
        raw = ask("E-mails adicionais, separados por vírgula")
        for item in [part.strip().lower() for part in raw.split(",") if part.strip()]:
            member_name = ask("Nome para " + item, default=item.split("@")[0])
            member_id, member_created = ensure_user(config, service_key, item, member_name, admin=False)
            upsert_member(config, member_id, member_name, "agente")
            print("  ✅ membro " + ("criado" if member_created else "reutilizado") + ": " + item)

    write_runtime_config(config, business_name, color)
    copy_widget()
    slug_default = "suporte-" + slugify(business_name)
    slug = slugify(ask("Nome do projeto Cloudflare Pages", default=slug_default))
    wrangler = command("wrangler")
    if not wrangler:
        wrangler = command("wrangler")
    if not wrangler:
        sair(1, "wrangler/npx não encontrado; instale o Wrangler e execute a Etapa 4 novamente.")
    if not ensure_pages_project(wrangler, slug, config):
        sair(1, "não foi possível preparar o projeto Pages.")
    suporte["pages_project"] = slug
    save_config(config)
    published = publish(wrangler, slug)
    if not published:
        sair(1, "o deploy não foi concluído; nada foi salvo como URL ativa.")
    ok, detail = smoke_hub(published)
    if not ok:
        sair(1, "falha no smoke do hub publicado: " + detail)
    asset_checks = {
        "/app.js": ["createClient", "sup_tickets"],
        "/style.css": ["--acento"],
        "/config.js": ["SUPORTE_CONFIG", "anonKey"],
    }
    for suffix, markers in asset_checks.items():
        asset_ok, asset_detail = smoke_asset(published + suffix, markers)
        if not asset_ok:
            sair(1, "falha na conferência de " + suffix + ": " + asset_detail)
    widget_ok, widget_detail = smoke_asset(published + "/suporte-widget.js", ["attachShadow", "textContent", "fetch"])
    if not widget_ok:
        sair(1, "falha na conferência do widget publicado: " + widget_detail)
    suporte["hub_url"] = published
    suporte["negocio_nome"] = business_name
    suporte["cor"] = color
    save_config(config)
    print("  ✅ hub conferido em " + published)
    print("  ✅ widget conferido em " + published + "/suporte-widget.js")
    print("\nComo embutir no seu site:")
    print('<script src="' + published + '/suporte-widget.js" data-endpoint="' + str(supabase_url).rstrip("/") + '/functions/v1/support-ai" data-anon-key="' + str(anon_key) + '" data-titulo="Fale com a gente" data-cor="' + color + '" defer></script>')
    print("\nEtapa 4 concluída e conferida em " + elapsed(started) + ".")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        erro("operação interrompida; nenhum deploy adicional foi tentado")
        sys.exit(130)
    except Exception as exc:
        erro("Etapa 4 não concluída: " + str(exc))
        sys.exit(1)
