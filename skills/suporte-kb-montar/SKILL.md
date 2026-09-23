---
name: suporte-kb-montar
description: "Monta a base inicial de conhecimento do suporte com IA entrevistando o aluno e lendo fontes que ele indicar. Use na Etapa 2 ou quando o aluno disser montar FAQ, base de conhecimento ou perguntas do atendimento."
model: sonnet
effort: medium
---

# Etapa 2 — montar a base de conhecimento

O objetivo é produzir pelo menos 15 itens confirmados pelo aluno. A base deve
responder ao cliente sem completar lacunas por imaginação. Uma resposta só pode
afirmar algo que veio do aluno ou de uma fonte que ele indicou.

## Entrevista

Faça as perguntas em blocos curtos e registre as respostas antes de criar JSON:

1. Qual é o nome do negócio, o nicho e o que ele oferece?
2. Quais produtos ou serviços existem? Para cada um, qual é o preço ou faixa que
   o próprio negócio divulga? Se o aluno não confirmar, deixe a informação fora.
3. Quais prazos de entrega, atendimento, execução, envio ou retorno são
   divulgados?
4. Quais são as políticas de troca, cancelamento, devolução, reembolso e
   garantia? Registre apenas a regra que o aluno confirmar.
5. Em quais dias e horários há atendimento? Há feriados ou exceções?
6. Quais canais oficiais existem: WhatsApp, site, e-mail, telefone, endereço,
   redes sociais ou portal? Peça o texto exato de cada link ou contato.
7. Quais são as 20 dúvidas mais comuns dos clientes? Peça exemplos reais e
   pergunte quais respostas podem ser usadas publicamente.

Peça ao aluno FAQ, site, manual, contrato, política, catálogo ou documento que
ele queira usar. Leia somente arquivos e URLs que ele indicar. Para cada fonte,
anote o nome ou URL em `fonte`; se uma fonte contradizer a fala atual do aluno,
pare e peça que ele escolha a versão correta. Não trate uma hipótese ou uma
pergunta sem resposta como fato.

## Construção e revisão

Crie uma lista JSON com exatamente estes campos em cada objeto:

```json
{"tema":"entrega","pergunta":"Qual é o prazo?","resposta":"Texto confirmado pelo aluno.","fonte":"aluno — entrevista de 2026-09-22"}
```

Cubra produtos/serviços, atendimento, prazos, políticas, canais e as dúvidas
comuns. Elimine duplicatas por pergunta. Se houver menos de 15 itens, volte à
entrevista: não preencha a contagem com respostas genéricas. Mostre a lista
inteira ao aluno, item por item, e peça correções. Só depois da confirmação,
grave atomicamente em:

```text
~/.operacao-ia/suporte/kb/itens.json
```

Use `Path.home()` em scripts; o caminho acima é apenas a forma de explicá-lo ao
aluno.

## Importação e conferência

Na raiz do repositório, rode:

```bash
python3 scripts/kb_importar.py --arquivo ~/.operacao-ia/suporte/kb/itens.json
python3 scripts/kb_importar.py --listar
```

Confira no resumo que todos os itens foram aceitos, que as perguntas repetidas
foram atualizadas em vez de duplicadas e que a contagem permanece em pelo menos
15. Se a fonte precisar de um nome uniforme, use explicitamente
`--substituir-fonte "nome confirmado pelo aluno"` e confira novamente. Registre
o caminho do JSON e o resultado de `--listar` como artefato da Etapa 2.

Nunca invente preço, prazo, política, canal, link ou resposta. Quando o aluno
não souber, escreva uma pergunta de retorno ou deixe o item fora da base.
