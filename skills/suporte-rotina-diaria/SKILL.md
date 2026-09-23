---
name: suporte-rotina-diaria
description: "Roda a rotina diária do suporte: lê os tickets abertos e as conversas da IA, redige resposta pra cada ticket usando só a base de conhecimento, pede aprovação do aluno na própria conversa, grava o que for aprovado e entrega o texto pronto (com link de WhatsApp) pra ele mandar pelo número do negócio. Também traz as perguntas pendentes da base que aprende pra aprovar ali mesmo. Use SEMPRE que o aluno disser: rotina de suporte, responder tickets, analisar suporte do dia, rodar o suporte, ver os tickets de hoje, o que chegou no suporte, revisar suporte, tickets pendentes, aprovar perguntas da base, rotina diária de suporte, /suporte-rotina-diaria."
model: claude-sonnet-5
effort: high
---

# Rotina diária do suporte com IA

Esta skill é o dia a dia depois que o Setup 16 está instalado (Etapas 1 a 7 já
concluídas). Ela complementa a Etapa 6 (`suporte-auditoria`): a auditoria mede
— conversas, custo, percentual resolvido pela IA — mas **não responde clientes,
não aprova candidatas e não altera a base**. Esta rotina faz exatamente as três
coisas que a auditoria deixa de fora.

A operação **não tem envio automático de WhatsApp**. O contato com o cliente é
sempre humano, pelo WhatsApp do próprio negócio: esta skill prepara o texto e o
link pronto, e quem aperta enviar é o aluno.

## 0. Coletar o dia

Na raiz do repositório:

```bash
python3 setup/rotina_suporte.py coletar --dias 1
```

Aumente `--dias` para cobrir um fim de semana ou retomar depois de alguns dias
sem rodar a rotina. O comando devolve um JSON com:

- `metricas`: os mesmos números da auditoria diária (conversas, tickets,
  custo, percentual do teto, uso do modelo forte, erros de IA).
- `tickets_abertos`: cada ticket que não está `resolvido`, já com a
  **conversa completa** (`mensagens`, em ordem) e as entradas da KB mais
  relacionadas (`kb_relacionada`, vindas de `sup_buscar_kb`).
- `candidatas_kb_pendentes`: as perguntas de `sup_kb_candidatas` com
  `status='pendente'`, ordenadas pelas mais recorrentes.
- `conversas_ia_periodo`: conversas em que a IA respondeu no período,
  agrupadas por conversa, com a confiança média e se escalou para ticket —
  é o material para achar pergunta recorrente e lacuna de KB (passo 4).

Leia o JSON inteiro antes de agir. Uma janela sem ticket aberto é um resultado
válido — não invente trabalho para preencher a rotina.

## 1. Responder cada ticket aberto

Para cada item de `tickets_abertos`, na ordem em que veio (prioridade alta
primeiro):

1. Leia a conversa completa (`mensagens`) e a `kb_relacionada` do próprio
   ticket.
2. Redija uma resposta **só com o que está confirmado**: a KB do negócio
   (`kb_relacionada` e, se precisar, o restante de `sup_kb`) e o que o
   cliente já disse na conversa. Nunca complete preço, prazo, política ou
   exceção que não esteja escrito em algum lugar — mesma regra da Etapa 2
   (`suporte-kb-montar`): "não invente respostas para o negócio do aluno".
3. Se a KB não cobre a dúvida, não force uma resposta — diga isso ao aluno e
   pergunte a ele, ou deixe o ticket para a próxima rodada depois que a KB
   for atualizada (passo 4).
4. **Mostre a resposta ao aluno na conversa** com o contexto mínimo (nome do
   contato, assunto, canal, o que ele perguntou) e peça aprovação. Ele pode
   aprovar como está, pedir edição, ou dizer para pular o ticket.

Só depois de aprovado, grave:

```bash
# salve o texto final num arquivo antes (edição feita na conversa, não solta no shell)
python3 setup/rotina_suporte.py responder --ticket <id> --texto-arquivo <caminho.txt>
python3 setup/rotina_suporte.py responder --ticket <id> --texto-arquivo <caminho.txt> --resolver
```

Sem `--resolver`, o ticket vai para `aguardando_cliente` (o cliente ainda
pode responder). Com `--resolver`, o ticket fecha — use quando a resposta já
resolve o caso e não há necessidade de aguardar retorno.

O comando grava a mensagem (`autor='humano'`) e o novo status, confere a
gravação lendo de volta, e devolve um JSON com o texto final e, quando o
ticket tem WhatsApp cadastrado, `whatsapp_link` — um link `https://wa.me/`
já com o texto preenchido. Entregue ao aluno, para cada ticket respondido:

- o texto final da resposta;
- o link pronto (`whatsapp_link`) quando houver WhatsApp, ou o
  `contato_email` quando o canal for e-mail/site e não houver WhatsApp — a
  rotina nunca manda a mensagem sozinha, só entrega o material pronto.

## 2. Perguntas pendentes da base que aprende

Para cada item de `candidatas_kb_pendentes`, traga **na conversa** — nunca
mande o aluno abrir o painel:

- a pergunta e o `contexto` (se houver);
- a `resposta_sugerida` existente, se já tiver uma;
- quantas vezes ela se repetiu (`ocorrencias`);
- a sua proposta de resposta final, só com informação que já apareceu na KB
  ou que o aluno confirmar ali mesmo.

Peça a decisão do aluno. Não afirme preço, prazo ou política em nome dele —
pergunte, exatamente como a Etapa 5 (`suporte-kb-aprender`) já exige.

**Aprovado** (o aluno confirma a pergunta e a resposta final):

```bash
python3 setup/rotina_suporte.py aprovar-kb --candidata <id> --resposta-arquivo <caminho.txt>
# pergunta e tema editados, se o aluno pediu ajuste:
python3 setup/rotina_suporte.py aprovar-kb --candidata <id> --pergunta "<pergunta final>" \
  --resposta-arquivo <caminho.txt> --tema "<tema>"
```

O comando insere (ou atualiza, se já existir uma pergunta equivalente) em
`sup_kb`, marca a candidata como `aprovada` e confere as duas gravações lendo
de volta.

**Não aprovado** (não é pergunta de KB, é duplicada, ou o aluno decide não
manter):

```bash
python3 setup/rotina_suporte.py descartar-kb --candidata <id>
```

Isso só marca a candidata como `rejeitada` — nada é gravado em `sup_kb`. Uma
candidata que precisa de informação que ainda não existe fica pendente; não
force uma decisão do aluno só para esvaziar a fila.

## 3. Perguntas recorrentes e lacunas da KB

Olhe `conversas_ia_periodo`: conversas com `confianca_media` baixa e
conversas que **não escalaram** mas repetem a mesma dúvida são sinal de
lacuna — a IA está respondendo com baixa segurança ou dando uma resposta
genérica porque a KB não tem o conteúdo certo. Cruze com
`candidatas_kb_pendentes`: uma pergunta com `ocorrencias` alto é prioridade.

Aponte ao aluno, em 1-2 linhas por item, o padrão encontrado (ex.: "3
conversas perguntaram sobre prazo de entrega e a IA respondeu de forma
genérica — não há isso na KB") e sugira o tema a acrescentar. Não crie a
entrada sozinho: ou ela já está em `candidatas_kb_pendentes` (trate pelo
passo 2), ou você propõe a pergunta+resposta e segue o mesmo fluxo de
aprovação do passo 2 depois que o aluno confirmar o conteúdo.

## 4. Relatório final

Feche com um resumo curto, sem tabela nem seção sem conteúdo:

- tickets respondidos (com número/assunto) e quantos foram resolvidos vs.
  aguardando o cliente;
- quantos itens novos entraram em `sup_kb` e quantas candidatas foram
  descartadas;
- lacunas de KB sugeridas que ainda não foram confirmadas;
- o que ficou pendente e por quê (ex.: "ticket #12 sem resposta — falta
  confirmar o prazo de troca").

Um dia sem ticket aberto e sem candidata pendente é um resultado válido:
diga isso em 1-2 linhas e encerre. Esta rotina nunca envia nada sozinha —
todo contato com o cliente sai como texto e link prontos para o aluno.

## Agendar a rotina

Esta skill roda uma sessão do Claude Code — não é um script de fundo, então
não usa `setup/agendador.py` (aquele agenda só `scripts/auditoria_diaria.py`,
que não conversa com ninguém). Para rodar todo dia automaticamente, use o
`/schedule` do próprio Claude Code, na raiz do repositório:

```text
/schedule
```

Crie uma rotina diária (por exemplo, às 8h) com um prompt como:

```text
Rode a rotina de suporte diária desta skill (suporte-rotina-diaria) no
repositório do Setup 16 e me traga os tickets e as candidatas de KB para eu
aprovar.
```

O agendamento é opcional — a rotina também funciona rodada manualmente,
sempre que o aluno quiser revisar o suporte.
