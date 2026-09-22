#!/usr/bin/env python3
"""Agendamento diário do blog do Setup 15, em qualquer sistema.

- macOS: LaunchAgent (launchagents/com.setup15.blog-daily.plist.template)
- Windows: Agendador de Tarefas (schtasks) chamando um wrapper .cmd
- Linux: crontab do usuário, numa linha marcada

Todas as funções devolvem {"ok": bool, "sistema": str, "detalhe": str} e nunca
lançam exceção por causa do sistema operacional.
"""
import getpass
import hashlib
import locale
import os
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parents[1]
BLOG_DIR = ROOT / "blog"
PLIST_TEMPLATE = ROOT / "launchagents" / "com.setup15.blog-daily.plist.template"
LABEL = "com.setup15.blog-daily"
WINDOWS_TASK = "ZXSetup15BlogDaily"  # prefixo; o nome real é por usuário (windows_task_name)
CRON_MARKER = "# zx-setup15-blog-daily"
# Comandos de sistema curtos (launchctl/schtasks/crontab): 30s é folga ampla.
CMD_TIMEOUT = 30


def _sistema(sistema):
    return sistema or platform.system()


def _home(home):
    return Path(home) if home else Path.home()


def plist_path(home=None):
    return _home(home) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def wrapper_path(home=None):
    return _home(home) / ".operacao-ia" / "bin" / "blog-daily.cmd"


def windows_task_name(usuario=None):
    """Nome da tarefa no Agendador, único por usuário do Windows.

    O Agendador tem um espaço de nomes da máquina inteira: com um nome fixo, o
    segundo aluno do mesmo computador falharia (ou sobrescreveria a tarefa do primeiro).
    """
    if usuario is None:
        usuario = os.environ.get("USERNAME") or getpass.getuser()
    limpo = re.sub(r"[^A-Za-z0-9_-]", "_", usuario)[:30] or "usuario"
    sufixo = hashlib.sha1(usuario.encode("utf-8")).hexdigest()[:6]
    return f"{WINDOWS_TASK}-{limpo}-{sufixo}"


def _result(ok, sistema, detalhe):
    return {"ok": bool(ok), "sistema": sistema, "detalhe": detalhe}


def _codec():
    return locale.getpreferredencoding(False) or "utf-8"


def _run(args, input_text=None):
    """Roda um comando curto; devolve CompletedProcess ou None se não rodou.

    Trafega bytes e decodifica aqui em vez de usar text=True porque o modo texto
    do subprocess traduz quebras de linha: um CR literal dentro de uma linha do
    crontab (ou da saída do schtasks) viraria LF e seria regravado como duas
    linhas, quebrando um agendamento alheio. surrogateescape completa o par: a
    saída localizada do schtasks e bytes legados do crontab não lançam e voltam
    idênticos na regravação.
    """
    codec = _codec()
    try:
        proc = subprocess.run(
            args,
            input=input_text.encode(codec, "surrogateescape") if input_text is not None else None,
            capture_output=True,
            timeout=CMD_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return subprocess.CompletedProcess(
        proc.args,
        proc.returncode,
        (proc.stdout or b"").decode(codec, "surrogateescape"),
        (proc.stderr or b"").decode(codec, "surrogateescape"),
    )


def _output(proc):
    if proc is None:
        return ""
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def _parse_hora(hora):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(hora or "").strip())
    if not match:
        return None
    hh, mm = int(match.group(1)), int(match.group(2))
    if hh > 23 or mm > 59:
        return None
    return hh, mm


# ---------------------------------------------------------------- macOS

def _gravar_atomico(path, conteudo, modo=0o644):
    """Grava trocando o arquivo de uma vez, com o modo explícito.

    O temporário nasce por mkstemp: nome imprevisível e criação exclusiva
    (O_CREAT|O_EXCL), no mesmo diretório do destino para o os.replace continuar
    atômico. Um nome fixo ".tmp" era duas falhas: se alguém deixasse um symlink
    com esse nome, o O_TRUNC seguia o link e truncava o arquivo apontado; e duas
    instalações ao mesmo tempo escreviam no mesmo temporário.

    O arquivo nasce 0600 (mkstemp) e só depois recebe `modo`: deixar o umask
    decidir criaria um plist gravável pelo grupo (umask 0002 dá 0664) e o launchd
    recusa carregar um plist assim — inclusive na restauração, que usaria a mesma
    rotina e deixaria o agendamento anterior sem voltar.
    """
    fd, tmp_nome = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as saida:
            saida.write(conteudo)
        if os.name != "nt":
            os.chmod(tmp_nome, modo)
        os.replace(tmp_nome, str(path))
    except Exception:
        try:
            os.unlink(tmp_nome)
        except OSError:
            pass
        raise


def _restaurar_plist(target, anterior):
    """Volta ao plist anterior depois de uma instalação frustrada. Sem plist anterior,
    remove o novo para não deixar um agendamento que ninguém carregou."""
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


def _instalar_darwin(blog_dir, node_bin, hh, mm, home):
    if not PLIST_TEMPLATE.is_file():
        return _result(False, "Darwin", f"Template não encontrado: {PLIST_TEMPLATE}")
    target = plist_path(home)
    node_dir = str(Path(node_bin).parent)
    plist = PLIST_TEMPLATE.read_text(encoding="utf-8")
    valores = {
        "BLOG_DIR": str(blog_dir),
        "HOME": str(_home(home)),
        "NODE_BIN": node_bin,
        "NODE": node_bin,
    }
    # Uma passada só: um caminho que contenha "{HOME}" não é reprocessado.
    plist = re.sub(
        r"\{(BLOG_DIR|HOME|NODE_BIN|NODE)\}",
        lambda m: xml_escape(valores[m.group(1)]),
        plist,
    )
    plist = re.sub(
        r"(<key>Hour</key>\s*<integer>)\d+(</integer>)", r"\g<1>%d\g<2>" % hh, plist
    )
    plist = re.sub(
        r"(<key>Minute</key>\s*<integer>)\d+(</integer>)", r"\g<1>%d\g<2>" % mm, plist
    )
    plist = plist.replace(
        "<string>/usr/local/bin:", "<string>" + xml_escape(node_dir) + ":/usr/local/bin:", 1
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    anterior = target.read_bytes() if target.exists() else None
    # Gravar antes de descarregar: se a escrita falhar (permissão, disco cheio), o
    # agendamento que já funcionava continua carregado.
    try:
        _gravar_atomico(target, plist.encode("utf-8"))
    except OSError as exc:
        return _result(
            False,
            "Darwin",
            f"Não foi possível gravar {target}: {exc}. O agendamento anterior segue ativo.",
        )
    if anterior is not None:
        _run(["launchctl", "unload", str(target)])
    # O job antigo pode seguir carregado mesmo sem plist; o load não o substituiria.
    carregado = _job_carregado()
    if carregado:
        _run(["launchctl", "remove", LABEL])
        carregado = _job_carregado()
    if carregado is None or carregado:
        _restaurar_plist(target, anterior)
        return _result(
            False,
            "Darwin",
            f"O job antigo {LABEL} não saiu do launchctl; nada foi reinstalado. "
            f"Rode: launchctl remove {LABEL} e instale de novo.",
        )
    carga = _run(["launchctl", "load", str(target)])
    if carga is None or carga.returncode != 0:
        recuperado = _restaurar_plist(target, anterior)
        extra = " O plist anterior foi restaurado e recarregado." if recuperado else ""
        return _result(
            False,
            "Darwin",
            f"LaunchAgent gravado em {target}, mas o launchctl load falhou: {_output(carga)}."
            + extra,
        )
    listed = _run(["launchctl", "list"])
    matches = [line for line in _output(listed).splitlines() if _label_carregado(line)]
    if matches:
        return _result(True, "Darwin", f"LaunchAgent instalado em {target}.\n" + "\n".join(matches))
    # load pode sair 0 sem carregar (job desabilitado por launchctl disable):
    # sem o label na lista, a instalação não vale e o plist anterior volta.
    recuperado = _restaurar_plist(target, anterior)
    extra = " O plist anterior foi restaurado e recarregado." if recuperado else ""
    return _result(
        False,
        "Darwin",
        f"LaunchAgent gravado em {target}, mas o launchctl não carregou o job "
        f"(confira com: launchctl list | grep {LABEL}; se estiver desabilitado, "
        f"launchctl enable gui/$(id -u)/{LABEL})." + extra,
    )


def _label_carregado(line):
    campos = line.split()
    return bool(campos) and campos[-1] == LABEL


def _job_carregado():
    """True/False conforme o launchctl list; None se não deu para consultar."""
    listed = _run(["launchctl", "list"])
    if listed is None or listed.returncode != 0:
        return None
    return any(_label_carregado(line) for line in _output(listed).splitlines())


def _remover_darwin(home):
    target = plist_path(home)
    if target.exists():
        _run(["launchctl", "unload", str(target)])
    carregado = _job_carregado()
    if carregado:
        # unload depende de ler o plist; remove pelo label funciona mesmo com o arquivo quebrado.
        _run(["launchctl", "remove", LABEL])
        carregado = _job_carregado()
    if carregado is None or carregado:
        return _result(
            False,
            "Darwin",
            f"Não foi possível confirmar que o job {LABEL} saiu do launchctl; "
            f"o plist foi preservado. Rode: launchctl remove {LABEL}",
        )
    if not target.exists():
        return _result(True, "Darwin", "LaunchAgent blog-daily: já removido")
    try:
        target.unlink()
    except OSError as exc:
        return _result(False, "Darwin", f"Não foi possível remover {target}: {exc}")
    return _result(True, "Darwin", "LaunchAgent blog-daily removido")


def _status_darwin(home):
    target = plist_path(home)
    carregado = bool(_job_carregado())
    return _result(
        target.exists() and carregado,
        "Darwin",
        f"plist {'existe' if target.exists() else 'ausente'}; "
        f"job {'carregado' if carregado else 'não carregado'}",
    )


# ---------------------------------------------------------------- Windows

def _cmd_quote(value):
    # Dentro de um .cmd, % precisa ser dobrado para não virar variável.
    return '"' + str(value).replace("%", "%%") + '"'


def _instalar_windows(blog_dir, node_bin, hh, mm, home):
    wrapper = wrapper_path(home)
    if "%" in str(wrapper):
        # O Agendador expande %VAR% no caminho da ação; o wrapper não seria encontrado.
        return _result(
            False,
            "Windows",
            f"A pasta do usuário ({_home(home)}) contém '%', que o Agendador de Tarefas "
            "interpreta como variável. Nada foi alterado.",
        )
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    blog = Path(blog_dir)
    linhas = [
        "@echo off",
        # Sem DisableDelayedExpansion, o cmd.exe come o "!" de caminhos como D:\Aulas!\blog
        # quando a expansão atrasada está ligada no registro do usuário.
        "setlocal EnableExtensions DisableDelayedExpansion",
        "chcp 65001 >nul",
        # pushd aceita caminho de rede (\\servidor\pasta), que o cd /d recusa;
        # se a pasta não abrir, a tarefa para em vez de rodar no diretório errado.
        "pushd " + _cmd_quote(blog) + " || exit /b 1",
        'if not exist "logs" mkdir "logs"',
        _cmd_quote(node_bin)
        + ' "generator\\daily_publish.js" >> "logs\\blog-daily.log" 2>> "logs\\blog-daily-err.log"',
        "set RC=%ERRORLEVEL%",
        "popd",
        "exit /b %RC%",
        "",
    ]
    anterior = wrapper.read_bytes() if wrapper.exists() else None
    _gravar_atomico(wrapper, "\r\n".join(linhas).encode("utf-8"))
    proc = _run([
        "schtasks", "/Create", "/SC", "DAILY", "/TN", windows_task_name(),
        "/TR", '"' + str(wrapper) + '"',
        "/ST", "%02d:%02d" % (hh, mm), "/F",
    ])
    if proc is None or proc.returncode != 0:
        # A tarefa antiga (se houver) continua apontando para o wrapper: devolve o conteúdo dela.
        if anterior is None:
            wrapper.unlink()
        else:
            _gravar_atomico(wrapper, anterior)
        if proc is None:
            return _result(False, "Windows", "Não foi possível executar o schtasks.")
        return _result(False, "Windows", "schtasks recusou a criação: " + _output(proc))
    detalhe = (
        f"Tarefa '{windows_task_name()}' criada no Agendador de Tarefas "
        f"(todo dia às {hh:02d}:{mm:02d}), executando {wrapper}."
    )
    if not _liberar_bateria_windows():
        # A tarefa existe e roda na tomada; só o caso "notebook na bateria" fica de fora.
        detalhe += (
            " Aviso: não foi possível liberar a execução na bateria. Em notebook fora da "
            "tomada o Windows pode pular o horário — em Agendador de Tarefas > Condições, "
            "desmarque 'Iniciar a tarefa somente se o computador estiver na rede elétrica'."
        )
    return _result(True, "Windows", detalhe)


def _liberar_bateria_windows():
    """schtasks /Create nasce com DisallowStartIfOnBatteries; o Agendador então pula o
    horário em notebook fora da tomada. Só o módulo ScheduledTasks do PowerShell muda isso.
    Falha aqui não derruba a instalação: a tarefa já existe e roda na rede elétrica."""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return False
    proc = _run([
        powershell, "-NoProfile", "-NonInteractive", "-Command",
        "Set-ScheduledTask -TaskName '%s' -Settings (New-ScheduledTaskSettingsSet "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable)"
        % windows_task_name(),
    ])
    return proc is not None and proc.returncode == 0


def _remover_windows(home):
    nome = windows_task_name()
    consulta = _run(["schtasks", "/Query", "/TN", nome])
    if consulta is None:
        return _result(False, "Windows", "Não foi possível executar o schtasks; nada foi removido.")
    partes = []
    if consulta.returncode == 0:
        proc = _run(["schtasks", "/Delete", "/TN", nome, "/F"])
        if proc is None or proc.returncode != 0:
            # O wrapper fica: apagá-lo deixaria a tarefa apontando para um arquivo inexistente.
            return _result(
                False,
                "Windows",
                f"schtasks não removeu a tarefa '{nome}': {_output(proc)}",
            )
        partes.append(f"Tarefa '{nome}' removida")
    else:
        # /Query falha tanto para "não existe" quanto para "acesso negado", e a mensagem
        # muda com o idioma do Windows. A lista completa decide sem depender do texto.
        lista = _run(["schtasks", "/Query", "/FO", "CSV", "/NH"])
        if lista is None or lista.returncode != 0:
            return _result(
                False,
                "Windows",
                f"Não foi possível confirmar se a tarefa '{nome}' existe; nada foi removido. "
                + _output(consulta),
            )
        if ('"\\' + nome + '"').lower() in _output(lista).lower():
            return _result(
                False,
                "Windows",
                f"A tarefa '{nome}' existe mas não pôde ser consultada; nada foi removido. "
                + _output(consulta),
            )
        partes.append(f"Tarefa '{nome}': já removida ou inexistente")
    wrapper = wrapper_path(home)
    try:
        if wrapper.exists():
            wrapper.unlink()
            partes.append("wrapper removido")
    except OSError as exc:
        return _result(False, "Windows", f"Não foi possível remover {wrapper}: {exc}")
    return _result(True, "Windows", "; ".join(partes))


def _status_windows(home):
    nome = windows_task_name()
    proc = _run(["schtasks", "/Query", "/TN", nome])
    existe = proc is not None and proc.returncode == 0
    return _result(
        existe,
        "Windows",
        _output(proc) if existe else f"Tarefa '{nome}' não encontrada",
    )


# ---------------------------------------------------------------- Linux

def _crontab_atual():
    if not shutil.which("crontab"):
        return None
    proc = _run(["crontab", "-l"])
    if proc is None:
        return None
    if proc.returncode != 0:
        # Só "no crontab for <user>" significa crontab vazio. Qualquer outra
        # falha (spool ilegível/corrompido, permissão, erro transitório do
        # cron) tem que abortar — nunca virar "" e sobrescrever os
        # agendamentos existentes do usuário.
        if "no crontab for" in _output(proc).lower():
            return ""
        return None
    return proc.stdout or ""


def _linha_nossa(line):
    # Só o marcador completo no FIM da linha; "# zx-setup15-blog-daily-backup" é de outra tarefa.
    texto = line.rstrip()
    return texto == CRON_MARKER or texto.endswith(" " + CRON_MARKER)


def _linhas_cron(texto):
    # split("\n"), nunca splitlines(): o crontab separa registros só por LF, e
    # splitlines() também quebraria dentro de um caminho com U+2028, \x0b ou \x0c.
    return texto.split("\n")


def _sem_marcador(texto):
    return [line for line in _linhas_cron(texto) if not _linha_nossa(line)]


def _gravar_crontab(linhas):
    conteudo = "\n".join(linhas).strip("\n")
    conteudo = conteudo + "\n" if conteudo else ""
    proc = _run(["crontab", "-"], input_text=conteudo)
    return proc is not None and proc.returncode == 0, _output(proc)


def _instalar_linux(blog_dir, node_bin, hh, mm):
    if any(c in str(blog_dir) + node_bin for c in "\\\n\r"):
        # O cron reinterpreta barra invertida e quebra de linha antes do shell.
        return _result(
            False,
            "Linux",
            "O caminho do blog ou do node contém barra invertida ou quebra de linha, "
            "que o cron não aceita. Mova o projeto para uma pasta com nome simples.",
        )
    atual = _crontab_atual()
    if atual is None:
        return _result(
            False,
            "Linux",
            "crontab não encontrado. Agende manualmente: "
            f"cd {shlex.quote(str(blog_dir))}; node generator/daily_publish.js",
        )
    comando = (
        f"cd {shlex.quote(str(blog_dir))} && {shlex.quote(node_bin)} "
        "generator/daily_publish.js >> logs/blog-daily.log 2>> logs/blog-daily-err.log"
    )
    # No crontab, % vira quebra de linha se não for escapado.
    comando = comando.replace("%", "\\%")
    linha = f"{mm} {hh} * * * {comando} {CRON_MARKER}"
    ok, saida = _gravar_crontab(_sem_marcador(atual) + [linha])
    if not ok:
        return _result(False, "Linux", "crontab recusou a gravação: " + saida)
    return _result(True, "Linux", f"Linha adicionada ao crontab (todo dia às {hh:02d}:{mm:02d}).")


def _remover_linux():
    atual = _crontab_atual()
    if atual is None:
        return _result(
            False,
            "Linux",
            "Não foi possível ler o crontab (comando ausente no PATH ou erro de leitura); "
            "confira com 'crontab -l' e apague a linha que termina em " + CRON_MARKER + ".",
        )
    if not any(_linha_nossa(line) for line in _linhas_cron(atual)):
        return _result(True, "Linux", "Agendamento blog-daily: já removido")
    ok, saida = _gravar_crontab(_sem_marcador(atual))
    if not ok:
        return _result(False, "Linux", "crontab recusou a gravação: " + saida)
    return _result(True, "Linux", "Linha do blog-daily removida do crontab")


def _status_linux():
    atual = _crontab_atual()
    existe = bool(atual) and any(_linha_nossa(line) for line in _linhas_cron(atual))
    return _result(existe, "Linux", "linha presente no crontab" if existe else "sem linha no crontab")


# ---------------------------------------------------------------- API

def _absoluto(caminho):
    """Caminho que continua valendo quando a tarefa roda de outro diretório.

    No Windows quem decide é PureWindowsPath: "/nodejs/node.exe" é enraizado mas
    NÃO tem unidade, e resolveria para a unidade corrente do processo — a tarefa
    diária começa em outra e o node some. abspath fixa a unidade.
    Fora do Windows, um caminho no estilo do Windows (C:\\...) é devolvido intacto:
    abspath prefixaria o cwd e inventaria um caminho que não existe.
    """
    if os.name == "nt":
        if PureWindowsPath(caminho).is_absolute():
            return caminho
        return os.path.abspath(caminho)
    if PurePosixPath(caminho).is_absolute() or PureWindowsPath(caminho).is_absolute():
        return caminho
    return os.path.abspath(caminho)


def _resolver_node(node_bin):
    """Caminho do node que continua válido quando a tarefa roda em outro diretório."""
    if not node_bin:
        achado = shutil.which("node")
    else:
        node = os.path.expanduser(str(node_bin))
        if not any(sep in node for sep in ("/", "\\")):
            # which devolve o caminho como está no PATH: uma entrada relativa
            # (./bin) voltaria relativa e o agendador não acharia o node.
            achado = shutil.which(node)
        else:
            achado = node
    return _absoluto(achado) if achado else achado


def _node_executavel(node):
    """No Windows quem decide é a extensão; no Unix, o bit de execução."""
    if not os.path.isfile(node):
        return False
    if os.name == "nt":
        return True
    return os.access(node, os.X_OK)


def instalar(
    hora="08:00",
    blog_dir=None,
    node_bin=None,
    sistema=None,
    home=None,
):
    # type: (str, Optional[Path], Optional[str], Optional[str], Optional[Path]) -> dict
    so = _sistema(sistema)
    parsed = _parse_hora(hora)
    if parsed is None:
        return _result(False, so, f"Hora inválida: {hora!r} (use HH:MM)")
    hh, mm = parsed
    if so not in ("Darwin", "Windows", "Linux"):
        return _result(
            False,
            so,
            f"Sistema {so} sem agendador suportado. Rode manualmente: node blog/generator/daily_publish.js",
        )
    # A preparação entra no try junto com a instalação: abspath consulta o cwd, e um
    # cwd apagado faz o FileNotFoundError escapar da API em vez de virar ok=False.
    try:
        # Caminho absoluto: o agendador roda a partir de outro diretório.
        blog = Path(os.path.abspath(str(Path(blog_dir).expanduser()))) if blog_dir else BLOG_DIR
        node = _resolver_node(node_bin)
        if not node:
            return _result(False, so, f"Node não foi encontrado ({node_bin or 'node'}); não foi possível agendar.")
        if not _node_executavel(node):
            # Antes de tocar no agendamento: um node sem permissão de execução trocaria
            # uma tarefa que funciona por outra que falha todo dia.
            return _result(
                False,
                so,
                f"{node} não é um arquivo executável; o agendamento atual não foi alterado.",
            )
        (blog / "logs").mkdir(parents=True, exist_ok=True)
        if so == "Darwin":
            return _instalar_darwin(blog, node, hh, mm, home)
        if so == "Windows":
            return _instalar_windows(blog, node, hh, mm, home)
        if so == "Linux":
            return _instalar_linux(blog, node, hh, mm)
    except OSError as exc:
        return _result(False, so, f"Não foi possível agendar: {exc}")
    return _result(
        False,
        so,
        f"Sistema {so} sem agendador suportado. Rode manualmente: node blog/generator/daily_publish.js",
    )


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
        return _result(False, so, f"Não foi possível remover o agendamento: {exc}")
    return _result(True, so, "Nenhum agendamento conhecido para este sistema")


def status(sistema=None, home=None):
    so = _sistema(sistema)
    try:
        if so == "Darwin":
            return _status_darwin(home)
        if so == "Windows":
            return _status_windows(home)
        if so == "Linux":
            return _status_linux()
    except OSError as exc:
        return _result(False, so, f"Não foi possível consultar o agendamento: {exc}")
    return _result(False, so, "Sistema sem agendador suportado")


if __name__ == "__main__":
    import json
    import sys

    acao = sys.argv[1] if len(sys.argv) > 1 else "status"
    funcoes = {"instalar": instalar, "remover": remover, "status": status}
    if acao not in funcoes:
        print("Uso: agendador.py [instalar|remover|status]")
        raise SystemExit(2)
    resultado = funcoes[acao]()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    raise SystemExit(0 if resultado["ok"] else 1)
