#!/usr/bin/env python3
"""Estado persistente do Setup 16, compatível com Python 3.9."""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "setup"))
from _comum import ESTADO_PATH, load_estado, save_estado

ETAPAS = ["1", "2", "3", "4", "5", "6", "7"]
ROTULOS = {
    "1": "Fundação do Supabase",
    "2": "Base de conhecimento inicial",
    "3": "Agente de suporte",
    "4": "Hub de tickets e widget",
    "5": "Base que aprende",
    "6": "Auditoria diária e agendamento",
    "7": "Auditoria técnica final",
}
ICONES = {"pending": "⏳", "in-progress": "🔄", "done": "✅"}


def _agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _novo():
    agora = _agora()
    return {
        "schema_version": 1,
        "created_at": agora,
        "updated_at": agora,
        "etapas": {etapa: {"status": "pending", "artifact": None} for etapa in ETAPAS},
    }


def ler():
    estado = load_estado()
    if not isinstance(estado, dict) or estado.get("schema_version") != 1:
        return _novo()
    etapas = estado.setdefault("etapas", {})
    for etapa in ETAPAS:
        atual = etapas.get(etapa)
        if not isinstance(atual, dict):
            etapas[etapa] = {"status": "pending", "artifact": None}
    return estado


def salvar(estado):
    estado["updated_at"] = _agora()
    save_estado(estado)


def validar(etapa):
    if str(etapa) not in ETAPAS:
        raise SystemExit("Etapa desconhecida: %s. Use 1, 2, 3, 4, 5, 6 ou 7." % etapa)
    return str(etapa)


def pode_iniciar(etapa):
    etapa = validar(etapa)
    estado = ler()
    indice = ETAPAS.index(etapa)
    for anterior in ETAPAS[:indice]:
        if estado["etapas"][anterior].get("status") != "done":
            return False, "Etapa %s (%s) ainda não foi concluída." % (anterior, ROTULOS[anterior])
    return True, "ok"


def proxima():
    estado = ler()
    for etapa in ETAPAS:
        if estado["etapas"][etapa].get("status") != "done":
            return etapa
    return None


def status(etapa, valor, artefato=None):
    etapa = validar(etapa)
    estado = ler()
    registro = estado["etapas"][etapa]
    registro["status"] = valor
    if valor == "in-progress":
        registro.setdefault("started_at", _agora())
    if valor == "done":
        registro["completed_at"] = _agora()
        if artefato:
            registro["artifact"] = artefato
    salvar(estado)


def cmd_status():
    estado = ler()
    print("Setup 16 — Sistema de Suporte com IA")
    print("Estado: %s\n" % ESTADO_PATH)
    for etapa in ETAPAS:
        registro = estado["etapas"][etapa]
        icone = ICONES.get(registro.get("status"), "⚠️")
        print("  %s. %s %s [%s]" % (etapa, icone, ROTULOS[etapa], registro.get("status")))
        if registro.get("artifact"):
            print("      artefato: %s" % registro["artifact"])
    seguinte = proxima()
    if seguinte is None:
        print("\nTodas as 7 etapas foram concluídas.")
    else:
        print("\nPróxima: Etapa %s — %s" % (seguinte, ROTULOS[seguinte]))


def cmd_continuar():
    seguinte = proxima()
    print("concluido" if seguinte is None else seguinte)


def cmd_can(args):
    if not args:
        raise SystemExit("Uso: estado.py can <etapa>")
    permitido, motivo = pode_iniciar(args[0])
    print(motivo)
    return 0 if permitido else 1


def cmd_start(args):
    if not args:
        raise SystemExit("Uso: estado.py start <etapa>")
    etapa = validar(args[0])
    permitido, motivo = pode_iniciar(etapa)
    if not permitido:
        raise SystemExit("bloqueado: " + motivo)
    estado = ler()
    atual = estado["etapas"][etapa].get("status")
    if atual == "done":
        print("Etapa %s já está concluída." % etapa)
        return
    status(etapa, "in-progress")
    print("Etapa %s iniciada." % etapa)


def cmd_done(args):
    if not args:
        raise SystemExit("Uso: estado.py done <etapa> [artefato]")
    etapa = validar(args[0])
    permitido, motivo = pode_iniciar(etapa)
    estado = ler()
    atual = estado["etapas"][etapa].get("status")
    if atual != "in-progress" or not permitido:
        raise SystemExit("não é possível concluir: " + (motivo if not permitido else "Etapa não foi iniciada."))
    status(etapa, "done", args[1] if len(args) > 1 else None)
    print("Etapa %s concluída." % etapa)


def cmd_redo(args):
    if not args:
        raise SystemExit("Uso: estado.py redo <etapa>")
    etapa = validar(args[0])
    estado = ler()
    for posterior in ETAPAS[ETAPAS.index(etapa):]:
        estado["etapas"][posterior] = {"status": "pending", "artifact": None}
    salvar(estado)
    print("Etapa %s e as etapas seguintes voltaram para pendente." % etapa)


def main(argv):
    comando = argv[0] if argv else "status"
    args = argv[1:]
    if comando == "status":
        cmd_status()
        return 0
    if comando == "continuar":
        cmd_continuar()
        return 0
    if comando == "can":
        return cmd_can(args)
    if comando == "start":
        cmd_start(args)
        return 0
    if comando == "done":
        cmd_done(args)
        return 0
    if comando == "redo":
        cmd_redo(args)
        return 0
    raise SystemExit("Comando desconhecido: %s. Use status, continuar, can, start, done ou redo." % comando)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
