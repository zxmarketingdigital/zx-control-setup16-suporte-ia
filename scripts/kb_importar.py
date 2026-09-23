#!/usr/bin/env python3
"""Valida e importa a base de conhecimento do Setup 16."""
import argparse
import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
from _comum import SUPORTE_DIR, load_config, supabase_rest


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(char for char in texto if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", texto.casefold()).strip()


def ler_json(caminho):
    try:
        return json.loads(Path(caminho).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit("Não foi possível ler o JSON: %s" % exc)


def validar_itens(valor):
    if not isinstance(valor, list):
        raise SystemExit("O arquivo deve conter uma lista JSON.")
    resultado = []
    vistos = set()
    for indice, item in enumerate(valor, 1):
        if not isinstance(item, dict):
            raise SystemExit("Item %s não é um objeto JSON." % indice)
        campos = ("tema", "pergunta", "resposta", "fonte")
        ausentes = [campo for campo in campos if not str(item.get(campo, "")).strip()]
        if ausentes:
            raise SystemExit("Item %s sem campos: %s" % (indice, ", ".join(ausentes)))
        limpo = {campo: str(item[campo]).strip() for campo in campos}
        chave = normalizar(limpo["pergunta"])
        if not chave:
            raise SystemExit("Item %s tem pergunta vazia." % indice)
        if chave in vistos:
            for anterior in resultado:
                if normalizar(anterior["pergunta"]) == chave:
                    anterior.update(limpo)
                    break
        else:
            vistos.add(chave)
            resultado.append(limpo)
    return resultado


def _erro_http(status, dados):
    if status < 200 or status >= 300:
        detalhe = dados if isinstance(dados, str) else json.dumps(dados, ensure_ascii=False)
        raise SystemExit("Supabase respondeu HTTP %s: %s" % (status, detalhe[:500]))


def listar(config):
    status, dados = supabase_rest(
        config,
        "GET",
        "/sup_kb?select=id,tema,pergunta,resposta,fonte,ativo&order=tema,pergunta",
    )
    _erro_http(status, dados)
    itens = dados if isinstance(dados, list) else []
    print("Itens ativos na KB: %s" % len([item for item in itens if item.get("ativo", True)]))
    for item in itens:
        if item.get("ativo", True):
            print("- [%s] %s — %s" % (item.get("tema", ""), item.get("pergunta", ""), item.get("fonte", "")))
    return itens


def exportar(config, caminho):
    itens = listar(config)
    destino = Path(caminho).expanduser()
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=str(destino.parent), prefix=".kb-export-", suffix=".json")
    try:
        with open(fd, "w", encoding="utf-8", closefd=True) as arquivo:
            json.dump(
                [
                    {campo: item.get(campo, "") for campo in ("tema", "pergunta", "resposta", "fonte")}
                    for item in itens
                    if item.get("ativo", True)
                ],
                arquivo,
                ensure_ascii=False,
                indent=2,
            )
        Path(temporario).replace(destino)
    except BaseException:
        try:
            Path(temporario).unlink()
        except OSError:
            pass
        raise
    print("Exportado para %s" % destino)


def importar(config, itens, fonte_override=None):
    status, existentes = supabase_rest(
        config,
        "GET",
        "/sup_kb?select=id,pergunta&limit=1000",
    )
    _erro_http(status, existentes)
    por_pergunta = {
        normalizar(item.get("pergunta")): item.get("id")
        for item in (existentes if isinstance(existentes, list) else [])
        if item.get("id")
    }
    contagem = Counter()
    atualizados = 0
    inseridos = 0
    for item in itens:
        item = dict(item)
        if fonte_override:
            item["fonte"] = fonte_override
        chave = normalizar(item["pergunta"])
        existente = por_pergunta.get(chave)
        if existente:
            status, dados = supabase_rest(config, "PATCH", "/sup_kb?id=eq.%s" % existente, item)
            atualizados += 1
        else:
            status, dados = supabase_rest(config, "POST", "/sup_kb", item)
            inseridos += 1
        _erro_http(status, dados)
        contagem[item["tema"]] += 1
    print("Importação conferida: %s inseridos, %s atualizados, %s itens únicos." % (inseridos, atualizados, len(itens)))
    for tema, quantidade in sorted(contagem.items()):
        print("- %s: %s" % (tema, quantidade))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Importa itens confirmados para sup_kb.")
    parser.add_argument("--arquivo", help="JSON com a lista de itens")
    parser.add_argument("--substituir-fonte", help="fonte confirmada para os itens importados")
    parser.add_argument("--listar", action="store_true", help="lista itens ativos")
    parser.add_argument("--exportar", help="exporta itens ativos para um JSON")
    args = parser.parse_args(argv)
    if not (args.arquivo or args.listar or args.exportar):
        parser.error("use --arquivo, --listar ou --exportar")
    config = load_config()
    if args.listar:
        listar(config)
    if args.exportar:
        exportar(config, args.exportar)
    if args.arquivo:
        itens = validar_itens(ler_json(args.arquivo))
        importar(config, itens, args.substituir_fonte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
