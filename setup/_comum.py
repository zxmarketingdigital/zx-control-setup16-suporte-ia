#!/usr/bin/env python3
"""Funções compartilhadas do Setup 16 — Sistema de Suporte com IA.

Só biblioteca padrão, compatível com Python 3.9 (nada de `str | None`).
Todo script de setup/ e scripts/ importa daqui; nenhum reimplementa leitura de
config ou chamada HTTP por conta própria.

Config do aluno: ~/.operacao-ia/config/config.json. Este setup NÃO exige setup
anterior: `ensure_config` cria o arquivo mínimo se não existir e a Etapa 1
coleta as credenciais do Supabase que faltarem. Se o aluno já tem outra
instalação, o arquivo existente é reaproveitado.
Instalações anteriores gravaram as mesmas chaves em DOIS formatos — aninhado
(config["email"]["api_key"]) e plano (config["resend_api_key"]). Por isso
toda leitura passa por `cfg_get`, que tenta os dois.
"""
import getpass
import json
import os
import shutil
import sys
import tempfile
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

HOME = Path.home()
OPERACAO = HOME / ".operacao-ia"
CONFIG_DIR = OPERACAO / "config"
CONFIG_PATH = CONFIG_DIR / "config.json"
SUPORTE_DIR = OPERACAO / "suporte"
ESTADO_PATH = SUPORTE_DIR / "estado.json"
REPO_ROOT = Path(__file__).resolve().parents[1]

# Chamadas HTTP curtas (REST do Supabase, Resend). Processo longo usa o
# próprio timeout do chamador. Override por env, valor inválido cai no default.
def _timeout_env(nome, default):
    # type: (str, int) -> int
    try:
        v = int(os.environ.get(nome, ""))
        return v if v > 0 else default
    except ValueError:
        return default


HTTP_TIMEOUT = _timeout_env("ZX_SUPORTE_HTTP_TIMEOUT", 30)

# Mapa: nome lógico -> caminhos possíveis no config.json (primeiro que existir vence).
_ALIASES = {
    "supabase_url": [("supabase_url",), ("supabase", "url")],
    "supabase_anon_key": [("supabase_anon_key",), ("supabase", "anon_key")],
    "supabase_service_role_key": [("supabase_service_role_key",), ("supabase", "service_role_key")],
    "supabase_project_id": [("supabase_project_id",), ("supabase", "project_id")],
    "resend_api_key": [("email", "api_key"), ("resend_api_key",)],
    "email_from": [("email", "from_email"), ("email_from",)],
    "email_aluno": [("email", "test_recipient"), ("email_aluno",)],
    "cloudflare_account_id": [("cloudflare_account_id",), ("cloudflare", "account_id")],
}


def load_config():
    # type: () -> Dict[str, Any]
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        print(f"⚠️  Não consegui ler {CONFIG_PATH} (JSON inválido). Nada foi alterado nele.")
        return {}


class ConfigBackupError(OSError):
    """Não foi possível guardar cópia de segurança do config; o original NÃO foi tocado."""


def backup_config_copy(path):
    # type: (Path) -> Path
    """Copia (copy2) o config para <nome>.bak-<AAAAmmdd-HHMMSS>[-N], sem sobrescrever backup existente.

    Confere que o destino existe com o mesmo tamanho. Em falha, o original fica intacto
    e levanta ConfigBackupError (só então o chamador pode recriar o config)."""
    path = Path(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = None
    try:
        n = 0
        while backup is None:
            candidate = path.with_name("%s.bak-%s%s" % (path.name, stamp, "-%d" % n if n else ""))
            try:
                # O_EXCL: a criação é atômica; se outro processo pegou o nome, tenta o próximo sufixo.
                fd = os.open(str(candidate), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                n += 1
                continue
            backup = candidate
            with os.fdopen(fd, "wb") as dst, open(str(path), "rb") as src:
                shutil.copyfileobj(src, dst)
            os.chmod(str(backup), 0o600)  # backup nunca herda permissao aberta do original
        if not backup.is_file() or backup.stat().st_size != path.stat().st_size:
            raise OSError("cópia de segurança incompleta")
    except OSError as e:
        try:
            if backup is not None and backup.is_file():
                backup.unlink()
        except OSError:
            pass
        msg = (f"Não consegui salvar uma cópia de segurança de {path}: {e}. "
               "Verifique a permissão da pasta e rode de novo.")
        print(f"❌ {msg}")
        raise ConfigBackupError(msg) from e
    return backup


def _backup_se_corrompido():
    # type: () -> Optional[Path]
    """Se config.json existe mas não é um objeto JSON válido, guarda uma cópia em
    config.json.bak-<timestamp> e devolve o caminho do backup. Senão, None."""
    if not CONFIG_PATH.is_file():
        return None
    try:
        dados = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            return None
    except (OSError, ValueError, RecursionError):
        pass
    return backup_config_copy(CONFIG_PATH)


def ensure_config():
    # type: () -> Tuple[Dict[str, Any], str]
    """Garante um config.json mínimo e devolve (config, descrição). NUNCA bloqueia.

    - ausente: cria {"phase_completed": 0}
    - corrompido: backup config.json.bak-<timestamp> e recria o mínimo
    - válido (instalação anterior): reaproveita sem alterar nada
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    backup = _backup_se_corrompido()
    if backup is not None:
        _gravar_atomico(CONFIG_PATH, json.dumps({"phase_completed": 0}, indent=2))
        return {"phase_completed": 0}, "estava inválido; backup em %s e recriado" % backup.name
    if not CONFIG_PATH.is_file():
        _gravar_atomico(CONFIG_PATH, json.dumps({"phase_completed": 0}, indent=2))
        return {"phase_completed": 0}, "criado (instalação nova, sem setup anterior)"
    return load_config(), "reaproveitado"


def _gravar_atomico(path, texto):
    # type: (Path, str) -> None
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(str(path), 0o600)
    except OSError:
        pass


def save_config(config):
    # type: (Dict[str, Any]) -> None
    backup = _backup_se_corrompido()  # ConfigBackupError: original fica intacto
    if backup is not None:
        print(f"⚠️  {CONFIG_PATH.name} estava inválido; backup salvo em {backup.name}.")
    _gravar_atomico(CONFIG_PATH, json.dumps(config, ensure_ascii=False, indent=2))


def cfg_get(config, nome, default=None):
    # type: (Dict[str, Any], str, Any) -> Any
    for caminho in _ALIASES.get(nome, [(nome,)]):
        atual = config  # type: Any
        ok = True
        for parte in caminho:
            if isinstance(atual, dict) and parte in atual:
                atual = atual[parte]
            else:
                ok = False
                break
        if ok and atual not in (None, ""):
            return atual
    return default


def suporte_cfg(config):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Bloco próprio do Setup 16 dentro do config.json (config['suporte'])."""
    bloco = config.get("suporte")
    if not isinstance(bloco, dict):
        bloco = {}
        config["suporte"] = bloco
    return bloco


def ask(pergunta, default=None, secret=False):
    # type: (str, Optional[str], bool) -> str
    sufixo = f" [{default}]" if default else ""
    while True:
        try:
            valor = getpass.getpass(f"{pergunta}: ") if secret else input(f"{pergunta}{sufixo}: ")
        except EOFError:
            valor = ""
        valor = valor.strip()
        if valor:
            return valor
        if default is not None:
            return default
        print("  (campo obrigatório)")


def http_json(metodo, url, headers=None, corpo=None, timeout=None):
    # type: (str, str, Optional[Dict[str, str]], Any, Optional[int]) -> Tuple[int, Any]
    """Faz a requisição e devolve (status, corpo_decodificado). Nunca lança por HTTP 4xx/5xx.

    Status 0 = falha de rede (corpo traz a mensagem). Quem chama decide o que é erro.
    """
    dados = None
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if corpo is not None:
        dados = json.dumps(corpo).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=dados, headers=hdrs, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout or HTTP_TIMEOUT) as resp:
            texto = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        texto = e.read().decode("utf-8", "replace")
        status = e.code
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)
    try:
        return status, json.loads(texto) if texto else None
    except ValueError:
        return status, texto


def supabase_url_canonica(url, ref=None):
    # type: (Any, Optional[str]) -> str
    """Devolve `https://<ref>.supabase.co` se `url` for exatamente isso; senão "".

    A service role key viaja nesta URL, então só aceitamos o domínio oficial do
    Supabase (ref = 20 letras/dígitos minúsculos). Se `ref` vier, o host precisa ser o dele.
    """
    texto = str(url or "").strip()
    if not texto or any(c.isspace() or c in "\\@" for c in texto):
        return ""
    try:
        partes = urllib.parse.urlsplit(texto)
        porta = partes.port
        host = partes.hostname or ""
    except ValueError:
        return ""
    achou = re.match(r"^([a-z0-9]{20})\.supabase\.co$", host)
    if (partes.scheme != "https" or not achou or porta not in (None, 443)
            or partes.query or partes.fragment or partes.path not in ("", "/")):
        return ""
    if ref and str(ref).strip() != achou.group(1):
        return ""
    return "https://%s.supabase.co" % achou.group(1)


def supabase_base(config):
    # type: (Dict[str, Any]) -> str
    """URL base validada do Supabase do aluno, ou "" (ausente ou fora de *.supabase.co)."""
    return supabase_url_canonica(cfg_get(config, "supabase_url", ""))


def supabase_rest(config, metodo, caminho, corpo=None, service=True, extra_headers=None):
    # type: (Dict[str, Any], str, str, Any, bool, Optional[Dict[str, str]]) -> Tuple[int, Any]
    """Chama o PostgREST do projeto do aluno. `caminho` começa com '/', ex.: '/sup_kb?select=id'."""
    base = supabase_base(config)
    chave = cfg_get(config, "supabase_service_role_key" if service else "supabase_anon_key", "")
    if not base or not chave:
        return 0, "Supabase não configurado (ou URL fora de https://<ref>.supabase.co) no config.json (rode a Etapa 1)."
    headers = {"apikey": chave, "Authorization": f"Bearer {chave}", "Prefer": "return=representation"}
    if extra_headers:
        headers.update(extra_headers)
    return http_json(metodo, f"{base}/rest/v1{caminho}", headers=headers, corpo=corpo)


def load_estado():
    # type: () -> Dict[str, Any]
    if not ESTADO_PATH.exists():
        return {}
    try:
        return json.loads(ESTADO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_estado(estado):
    # type: (Dict[str, Any]) -> None
    _gravar_atomico(ESTADO_PATH, json.dumps(estado, ensure_ascii=False, indent=2))


def ok(msg):
    # type: (str) -> None
    print(f"  ✅ {msg}")


def aviso(msg):
    # type: (str) -> None
    print(f"  ⚠️  {msg}")


def erro(msg):
    # type: (str) -> None
    print(f"  ❌ {msg}")


def mascarar(valor):
    # type: (Optional[str]) -> str
    if not valor:
        return "(vazio)"
    v = str(valor)
    return v[:4] + "…" + v[-4:] if len(v) > 12 else "****"


def sair(codigo, msg=None):
    # type: (int, Optional[str]) -> None
    if msg:
        (erro if codigo else ok)(msg)
    sys.exit(codigo)


__all__ = [
    "HOME", "OPERACAO", "CONFIG_DIR", "CONFIG_PATH", "SUPORTE_DIR", "ESTADO_PATH", "REPO_ROOT",
    "HTTP_TIMEOUT", "load_config", "ensure_config", "save_config", "cfg_get", "suporte_cfg", "ask", "http_json",
    "supabase_rest", "load_estado", "save_estado", "ok", "aviso", "erro", "mascarar", "sair",
]

if __name__ == "__main__":
    c = load_config()
    for k in _ALIASES:
        v = cfg_get(c, k)
        print(f"{k:28} {'✅' if v else '—'}")
