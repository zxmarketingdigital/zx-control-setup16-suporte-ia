#!/usr/bin/env python3
"""Agendamento diário da auditoria do suporte em macOS, Windows e Linux."""
import getpass
import hashlib
import json
import locale
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from xml.sax.saxutils import escape as xml_escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comum import SUPORTE_DIR

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "auditoria_diaria.py"
LOG_DIR = SUPORTE_DIR / "logs"
PLIST_TEMPLATE = ROOT / "launchagents" / "com.zxsuporte.auditoria.plist.template"
LABEL = "com.zxsuporte.auditoria"
WINDOWS_TASK = "ZXSuporteAuditoria"
CRON_MARKER = "# zx-suporte-auditoria"
CMD_TIMEOUT = 30


def _sistema(sistema):
    return sistema or platform.system()


def _home(home):
    return Path(home) if home else Path.home()


def plist_path(home=None):
    return _home(home) / "Library" / "LaunchAgents" / (LABEL + ".plist")


def wrapper_path(home=None):
    return _home(home) / ".operacao-ia" / "bin" / "suporte-auditoria.cmd"


def windows_task_name(usuario=None):
    usuario = usuario or os.environ.get("USERNAME") or getpass.getuser()
    limpo = re.sub(r"[^A-Za-z0-9_-]", "_", usuario)[:30] or "usuario"
    sufixo = hashlib.sha1(usuario.encode("utf-8")).hexdigest()[:6]
    return "%s-%s-%s" % (WINDOWS_TASK, limpo, sufixo)


def _result(ok, sistema, detalhe):
    return {"ok": bool(ok), "sistema": sistema, "detalhe": detalhe}


def _codec():
    return locale.getpreferredencoding(False) or "utf-8"


def _run(args, input_text=None):
    try:
        proc = subprocess.run(
            args,
            input=input_text.encode(_codec(), "surrogateescape") if input_text is not None else None,
            capture_output=True,
            timeout=CMD_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    codec = _codec()
    return subprocess.CompletedProcess(
        proc.args,
        proc.returncode,
        (proc.stdout or b"").decode(codec, "surrogateescape"),
        (proc.stderr or b"").decode(codec, "surrogateescape"),
    )


def _output(proc):
    return "" if proc is None else ((proc.stdout or "") + (proc.stderr or "")).strip()


def _parse_hora(hora):
    encontro = re.fullmatch(r"(\d{1,2}):(\d{2})", str(hora or "").strip())
    if not encontro:
        return None
    hh, mm = int(encontro.group(1)), int(encontro.group(2))
    return (hh, mm) if hh <= 23 and mm <= 59 else None


def _gravar_atomico(path, conteudo, modo=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, nome = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as arquivo:
            arquivo.write(conteudo)
        if os.name != "nt":
            os.chmod(nome, modo)
        os.replace(nome, str(path))
    except BaseException:
        try:
            os.unlink(nome)
        except OSError:
            pass
        raise


def _restaurar_plist(target, anterior):
    try:
        if anterior is None:
            if target.exists():
                target.unlink()
            return False
        _gravar_atomico(target, anterior)
    except OSError:
        return False
    carga = _run(["launchctl", "load", str(target)])
    return carga is not None and carga.returncode == 0


def _label_carregado(linha):
    campos = linha.split()
    return bool(campos) and campos[-1] == LABEL


def _job_carregado():
    listado = _run(["launchctl", "list"])
    if listado is None or listado.returncode != 0:
        return None
    return any(_label_carregado(linha) for linha in _output(listado).splitlines())


def _instalar_darwin(script, python_bin, hh, mm, home):
    if not PLIST_TEMPLATE.is_file():
        return _result(False, "Darwin", "Template não encontrado: %s" % PLIST_TEMPLATE)
    target = plist_path(home)
    texto = PLIST_TEMPLATE.read_text(encoding="utf-8")
    valores = {
        "ROOT": str(ROOT), "SCRIPT": str(script), "PYTHON_BIN": python_bin,
        "PYTHON_DIR": str(Path(python_bin).parent), "HOME": str(_home(home)),
        "LOG_DIR": str(_home(home) / ".operacao-ia" / "suporte" / "logs"),
    }
    texto = re.sub(r"\{(ROOT|SCRIPT|PYTHON_BIN|PYTHON_DIR|HOME|LOG_DIR)\}", lambda m: xml_escape(valores[m.group(1)]), texto)
    texto = re.sub(r"(<key>Hour</key>\s*<integer>)\d+(</integer>)", r"\g<1>%d\g<2>" % hh, texto)
    texto = re.sub(r"(<key>Minute</key>\s*<integer>)\d+(</integer>)", r"\g<1>%d\g<2>" % mm, texto)
    target.parent.mkdir(parents=True, exist_ok=True)
    anterior = target.read_bytes() if target.exists() else None
    try:
        _gravar_atomico(target, texto.encode("utf-8"))
    except OSError as exc:
        return _result(False, "Darwin", "Não foi possível gravar %s: %s" % (target, exc))
    if anterior is not None:
        _run(["launchctl", "unload", str(target)])
    carregado = _job_carregado()
    if carregado:
        _run(["launchctl", "remove", LABEL])
        carregado = _job_carregado()
    if carregado is None or carregado:
        _restaurar_plist(target, anterior)
        return _result(False, "Darwin", "não foi possível retirar o agendamento anterior")
    carga = _run(["launchctl", "load", str(target)])
    if carga is None or carga.returncode != 0:
        extra = " O anterior foi restaurado." if _restaurar_plist(target, anterior) else ""
        return _result(False, "Darwin", "launchctl load falhou: %s.%s" % (_output(carga), extra))
    listado = _run(["launchctl", "list"])
    if listado is not None and any(_label_carregado(linha) for linha in _output(listado).splitlines()):
        return _result(True, "Darwin", "LaunchAgent instalado em %s" % target)
    extra = " O anterior foi restaurado." if _restaurar_plist(target, anterior) else ""
    return _result(False, "Darwin", "launchctl não confirmou o label.%s" % extra)


def _cmd_quote(valor):
    return '"' + str(valor).replace("%", "%%") + '"'


def _instalar_windows(script, python_bin, hh, mm, home):
    wrapper = wrapper_path(home)
    if "%" in str(wrapper):
        return _result(False, "Windows", "o caminho do usuário contém %, incompatível com schtasks")
    log_dir = _home(home) / ".operacao-ia" / "suporte" / "logs"
    linhas = [
        "@echo off", "setlocal EnableExtensions DisableDelayedExpansion", "chcp 65001 >nul",
        "if not exist " + _cmd_quote(log_dir) + " mkdir " + _cmd_quote(log_dir),
        "pushd " + _cmd_quote(ROOT) + " || exit /b 1",
        _cmd_quote(python_bin) + " " + _cmd_quote(script) + " >> " + _cmd_quote(log_dir / "auditoria-diaria.log") + " 2>> " + _cmd_quote(log_dir / "auditoria-diaria-err.log"),
        "set RC=%ERRORLEVEL%", "popd", "exit /b %RC%", "",
    ]
    anterior = wrapper.read_bytes() if wrapper.exists() else None
    _gravar_atomico(wrapper, "\r\n".join(linhas).encode("utf-8"))
    proc = _run(["schtasks", "/Create", "/SC", "DAILY", "/TN", windows_task_name(), "/TR", '"' + str(wrapper) + '"', "/ST", "%02d:%02d" % (hh, mm), "/F"])
    if proc is None or proc.returncode != 0:
        if anterior is None:
            wrapper.unlink()
        else:
            _gravar_atomico(wrapper, anterior)
        return _result(False, "Windows", "schtasks recusou a criação: %s" % _output(proc))
    return _result(True, "Windows", "Tarefa %s instalada às %02d:%02d" % (windows_task_name(), hh, mm))


def _crontab_atual():
    if not shutil.which("crontab"):
        return None
    proc = _run(["crontab", "-l"])
    if proc is None:
        return None
    if proc.returncode != 0:
        return "" if "no crontab for" in _output(proc).lower() else None
    return proc.stdout or ""


def _linha_nossa(linha):
    texto = linha.rstrip()
    return texto == CRON_MARKER or texto.endswith(" " + CRON_MARKER)


def _gravar_crontab(linhas):
    conteudo = "\n".join(linhas).strip("\n")
    conteudo = conteudo + "\n" if conteudo else ""
    proc = _run(["crontab", "-"], conteudo)
    return proc is not None and proc.returncode == 0, _output(proc)


def _instalar_linux(script, python_bin, hh, mm):
    caminho = str(ROOT) + str(script) + str(python_bin)
    if any(char in caminho for char in "\\\n\r"):
        return _result(False, "Linux", "há barra invertida ou quebra de linha em um caminho")
    atual = _crontab_atual()
    if atual is None:
        return _result(False, "Linux", "crontab ausente ou ilegível; nenhum agendamento foi alterado")
    log = str(LOG_DIR)
    comando = "cd %s && %s %s >> %s 2>> %s" % (shlex.quote(str(ROOT)), shlex.quote(python_bin), shlex.quote(str(script)), shlex.quote(log + "/auditoria-diaria.log"), shlex.quote(log + "/auditoria-diaria-err.log"))
    linha = "%d %d * * * %s %s" % (mm, hh, comando.replace("%", "\\%"), CRON_MARKER)
    linhas = [atual_linha for atual_linha in atual.split("\n") if not _linha_nossa(atual_linha)]
    ok, saida = _gravar_crontab(linhas + [linha])
    return _result(ok, "Linux", "linha instalada às %02d:%02d" % (hh, mm) if ok else "crontab recusou: " + saida)


def _remover_darwin(home):
    target = plist_path(home)
    if target.exists():
        _run(["launchctl", "unload", str(target)])
    carregado = _job_carregado()
    if carregado:
        _run(["launchctl", "remove", LABEL])
        carregado = _job_carregado()
    if carregado is None or carregado:
        return _result(False, "Darwin", "não foi possível confirmar a remoção")
    if target.exists():
        try:
            target.unlink()
        except OSError as exc:
            return _result(False, "Darwin", str(exc))
    return _result(True, "Darwin", "LaunchAgent removido")


def _remover_windows(home):
    nome = windows_task_name()
    consulta = _run(["schtasks", "/Query", "/TN", nome])
    if consulta is None:
        return _result(False, "Windows", "schtasks não disponível")
    if consulta.returncode == 0:
        removido = _run(["schtasks", "/Delete", "/TN", nome, "/F"])
        if removido is None or removido.returncode != 0:
            return _result(False, "Windows", "não foi possível remover a tarefa")
    wrapper = wrapper_path(home)
    if wrapper.exists():
        wrapper.unlink()
    return _result(True, "Windows", "tarefa e wrapper removidos")


def _remover_linux():
    atual = _crontab_atual()
    if atual is None:
        return _result(False, "Linux", "não foi possível ler o crontab")
    if not any(_linha_nossa(linha) for linha in atual.split("\n")):
        return _result(True, "Linux", "linha já ausente")
    ok, saida = _gravar_crontab([linha for linha in atual.split("\n") if not _linha_nossa(linha)])
    return _result(ok, "Linux", "linha removida" if ok else "crontab recusou: " + saida)


def _resolver_python(python_bin):
    candidato = python_bin or sys.executable
    if not candidato:
        candidato = shutil.which("python3") or shutil.which("python")
    elif not any(sep in str(candidato) for sep in ("/", "\\")):
        candidato = shutil.which(str(candidato))
    return _absoluto(candidato) if candidato else None


def _absoluto(caminho):
    if os.name == "nt":
        return caminho if PureWindowsPath(caminho).is_absolute() else os.path.abspath(caminho)
    if PurePosixPath(caminho).is_absolute() or PureWindowsPath(caminho).is_absolute():
        return caminho
    return os.path.abspath(caminho)


def _executavel(caminho):
    return bool(caminho and os.path.isfile(caminho) and (os.name == "nt" or os.access(caminho, os.X_OK)))


def instalar(hora="08:00", projeto_dir=None, python_bin=None, sistema=None, home=None):
    so = _sistema(sistema)
    parsed = _parse_hora(hora)
    if parsed is None:
        return _result(False, so, "Hora inválida: %r (use HH:MM)" % hora)
    hh, mm = parsed
    if so not in ("Darwin", "Windows", "Linux"):
        return _result(False, so, "sistema sem agendador suportado")
    try:
        script = Path(projeto_dir).expanduser().resolve() / "scripts" / "auditoria_diaria.py" if projeto_dir else SCRIPT
        python = _resolver_python(python_bin)
        if not script.is_file():
            return _result(False, so, "script não encontrado: %s" % script)
        if not _executavel(python):
            return _result(False, so, "Python não é executável: %s" % (python or "ausente"))
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if so == "Darwin":
            return _instalar_darwin(script, python, hh, mm, home)
        if so == "Windows":
            return _instalar_windows(script, python, hh, mm, home)
        return _instalar_linux(script, python, hh, mm)
    except OSError as exc:
        return _result(False, so, "não foi possível agendar: %s" % exc)


def remover(sistema=None, home=None):
    so = _sistema(sistema)
    try:
        if so == "Darwin":
            return _remover_darwin(home)
        if so == "Windows":
            return _remover_windows(home)
        if so == "Linux":
            return _remover_linux()
    except OSError as exc:
        return _result(False, so, "não foi possível remover: %s" % exc)
    return _result(True, so, "nenhum agendamento conhecido")


def status(sistema=None, home=None):
    so = _sistema(sistema)
    try:
        if so == "Darwin":
            target = plist_path(home)
            return _result(target.exists() and bool(_job_carregado()), "Darwin", "plist e job conferidos" if target.exists() else "plist ausente")
        if so == "Windows":
            proc = _run(["schtasks", "/Query", "/TN", windows_task_name()])
            return _result(proc is not None and proc.returncode == 0, "Windows", _output(proc) if proc is not None else "schtasks ausente")
        if so == "Linux":
            atual = _crontab_atual()
            existe = bool(atual) and any(_linha_nossa(linha) for linha in atual.split("\n"))
            return _result(existe, "Linux", "linha presente" if existe else "linha ausente")
    except OSError as exc:
        return _result(False, so, "não foi possível consultar: %s" % exc)
    return _result(False, so, "sistema sem agendador suportado")


if __name__ == "__main__":
    acao = sys.argv[1] if len(sys.argv) > 1 else "status"
    hora = "08:00"
    if "--hora" in sys.argv:
        indice = sys.argv.index("--hora")
        if indice + 1 < len(sys.argv):
            hora = sys.argv[indice + 1]
    funcoes = {"instalar": instalar, "remover": remover, "status": status}
    if acao not in funcoes:
        print("Uso: agendador.py [instalar|remover|status] [--hora HH:MM]")
        raise SystemExit(2)
    resultado = instalar(hora=hora) if acao == "instalar" else funcoes[acao]()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    raise SystemExit(0 if resultado.get("ok") else 1)
