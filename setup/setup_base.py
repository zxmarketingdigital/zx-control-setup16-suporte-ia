#!/usr/bin/env python3
"""Etapa 0: prepara a pasta local do Sistema de Suporte com IA."""
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _comum import SUPORTE_DIR, load_estado, save_estado


PLANO = [
    (1, "Fundação", "aplicar a migration e conectar o Supabase"),
    (2, "Base de conhecimento", "montar e importar os itens da KB"),
    (3, "Agente", "configurar o provedor e publicar a Edge Function"),
    (4, "Hub", "publicar a fila de tickets e criar o administrador"),
    (5, "Aprendizado", "aprovar candidatas e ampliar a base"),
    (6, "Auditoria", "instalar a auditoria diária por e-mail"),
]
ESTADO_ETAPAS = ["1", "2", "3", "4", "5", "6", "7"]


def _agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main():
    inicio = time.monotonic()
    try:
        (SUPORTE_DIR / "logs").mkdir(parents=True, exist_ok=True)
        (SUPORTE_DIR / "kb").mkdir(parents=True, exist_ok=True)
        estado = load_estado()
        agora = _agora()
        if not isinstance(estado, dict) or estado.get("schema_version") != 1:
            estado = {"schema_version": 1, "created_at": agora, "updated_at": agora, "etapas": {}}
        estado.setdefault("created_at", agora)
        estado["updated_at"] = agora
        etapas = estado.setdefault("etapas", {})
        for numero in ESTADO_ETAPAS:
            atual = etapas.get(numero)
            if not isinstance(atual, dict):
                etapas[numero] = {"status": "pending", "artifact": None}
            else:
                if atual.get("status") == "pendente":
                    atual["status"] = "pending"
                atual.setdefault("status", "pending")
                atual.setdefault("artifact", None)
        save_estado(estado)
    except OSError as exc:
        print("❌ Não foi possível preparar %s: %s" % (SUPORTE_DIR, exc))
        return 1

    print("Pasta local pronta: %s" % SUPORTE_DIR)
    print("\nPlano das 6 etapas:")
    for numero, nome, descricao in PLANO:
        status = estado["etapas"][str(numero)].get("status", "pending")
        print("  Etapa %d — %-22s [%s] — %s" % (numero, nome, status, descricao))
    print("\nEtapa 0 concluída em %.2fs." % (time.monotonic() - inicio))
    return 0


if __name__ == "__main__":
    sys.exit(main())
