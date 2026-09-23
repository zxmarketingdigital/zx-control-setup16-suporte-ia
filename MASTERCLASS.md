# Masterclass — implantando o suporte com IA

Roteiro de aula para o aluno acompanhar a instalação no próprio ambiente. Os
vídeos podem ser hospedados no Bunny e vinculados depois.

## Aula 1 — visão do sistema

Explique o caminho cliente → canal → Edge Function → base de conhecimento →
resposta ou atendimento humano. Mostre por que uma resposta só deve usar fatos
confirmados.

Vídeo: `BUNNY_GUID_1`

## Aula 2 — preparação

Confira os Setups 1 e 2, a configuração local e as ferramentas disponíveis.
Mostre como executar o clone e iniciar o Claude Code. Reforce que chaves entram
no prompt seguro do script, não no chat.

Vídeo: `BUNNY_GUID_2`

## Aula 3 — Etapas 1 a 3

Execute a fundação, monte a KB em entrevista e configure o agente. Pare em cada
conferência: tabelas respondendo, itens confirmados, `ping` e mensagem de teste.

Vídeo: `BUNNY_GUID_3`

## Aula 4 — Etapas 4 e 5

Publique o hub, crie o membro, teste o widget e abra uma candidata no fluxo de
aprendizado. Mostre a revisão humana antes de qualquer item entrar na KB ativa.

Vídeo: `BUNNY_GUID_4`

## Aula 5 — Etapa 6 e auditoria final

Gere o relatório com `--dry-run --sem-email`, revise as métricas, configure o
agendamento quando estiver aprovado e execute `setup/audit.py`. Explique quais
alertas precisam de ação humana e quais são apenas ausência de dados.

Vídeo: `BUNNY_GUID_5`

## Encerramento

Peça ao aluno para repetir os comandos de status, auditoria local e auditoria
técnica. A instalação só está encerrada quando as conferências correspondentes
estiverem registradas e o aluno souber como revisar a base.
