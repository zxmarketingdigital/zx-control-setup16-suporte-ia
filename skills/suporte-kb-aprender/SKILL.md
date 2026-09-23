---
name: suporte-kb-aprender
description: "Processa candidatas pendentes da base que aprende do suporte com aprovação explícita do aluno. Use na Etapa 5, depois do hub estar acessível."
model: sonnet
effort: medium
---

# Etapa 5 — base que aprende

Esta etapa transforma dúvidas que chegaram ao atendimento em itens úteis, mas
nenhuma sugestão vira resposta pública sem confirmação do aluno.

## 1. Ler as candidatas

Na raiz do repositório, carregue a configuração e liste as candidatas:

```bash
python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('setup').resolve()))
from _comum import load_config, supabase_rest
c = load_config()
status, dados = supabase_rest(c, 'GET', '/sup_kb_candidatas?status=eq.pendente&order=ocorrencias.desc,created_at.asc')
print('HTTP', status)
for item in dados if isinstance(dados, list) else []:
    print(item.get('id'), item.get('ocorrencias'), item.get('pergunta'), item.get('contexto'))
PY
```

Leia a pergunta, o contexto e a sugestão existente. Agrupe perguntas que são
claramente a mesma dúvida, mas não misture assuntos diferentes só para reduzir
a lista.

## 2. Confirmar o conteúdo

Para cada candidata, pergunte ao aluno qual é a resposta oficial, para quem ela
se aplica, se há exceção e qual fonte deve ser registrada. Se a informação não
for confirmada, mantenha a candidata pendente. Não derive fatos de uma resposta
da IA, de uma suposição ou de uma conversa incompleta.

Mostre ao aluno uma prévia com `tema`, `pergunta`, `resposta` e `fonte`. Ajuste
linguagem, canal e escopo até ele aprovar cada item.

## 3. Gravar a aprovação

Grave os itens aprovados em um arquivo temporário dentro de
`~/.operacao-ia/suporte/kb/` e depois copie o conteúdo confirmado para
`itens.json` usando a escrita atômica do script de importação. Rode:

```bash
python3 scripts/kb_importar.py --arquivo ~/.operacao-ia/suporte/kb/itens.json
python3 scripts/kb_importar.py --listar
```

Confira a pergunta normalizada, a resposta e a fonte no retorno. Depois marque
cada candidata aprovada, individualmente, usando REST com `service_role`:

```text
PATCH /rest/v1/sup_kb_candidatas?id=eq.<ID>
{"status":"aprovada","resposta_sugerida":"<resposta confirmada>"}
```

Use `supabase_rest` e não imprima chaves. Para uma candidata que não deve ser
aproveitada, peça a decisão do aluno e só então marque `rejeitada`. Se a resposta
precisar de informação futura, mantenha `pendente`.

## 4. Concluir

Confirme por uma nova listagem que os itens aprovados aparecem ativos em
`sup_kb`, que as candidatas correspondentes não continuam pendentes e que não
há duplicatas por pergunta. O artefato da Etapa 5 é o log dessa listagem e o
arquivo `itens.json` atualizado.
