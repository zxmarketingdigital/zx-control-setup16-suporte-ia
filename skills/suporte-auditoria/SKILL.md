---
name: suporte-auditoria
description: "Executa e interpreta a auditoria diária do sistema de suporte com IA, com relatório local e envio opcional por Resend. Use na Etapa 6 ou ao investigar saúde do suporte."
model: sonnet
effort: medium
---

# Etapa 6 — auditoria diária

A auditoria cobre a janela das últimas 24 horas por padrão. Para histórico,
use `--dias N`. O script consulta somente as tabelas `sup_*`, gera um relatório
HTML escapado e grava uma cópia em `~/.operacao-ia/suporte/logs/`.

## Primeiro uso: somente conferência local

Rode sempre antes do agendamento:

```bash
python3 scripts/auditoria_diaria.py --dry-run --sem-email
```

`--dry-run` é uma decisão de execução: o script não chama o endpoint de envio
de e-mail. `--sem-email` também impede o envio e imprime o resumo. Os dois
modos são respeitados antes de qualquer leitura de chave ou requisição ao
Resend. Confira a janela, o caminho do HTML e as métricas.

## Métricas conferidas

O relatório precisa mostrar: conversas distintas, mensagens, percentual
resolvido pela IA, tickets abertos/novos/resolvidos, backlog com mais de 24
horas, custo em USD e percentual do teto configurado, percentual de chamadas no
modelo forte, erros de IA e as cinco candidatas pendentes mais recorrentes.
Uma janela sem dados é um resultado vazio, não uma prova de que o sistema está
saudável: confira também o HTTP de cada tabela no log.

## Envio e agendamento

Só depois de o aluno revisar o HTML e confirmar o destinatário, execute sem os
modos de bloqueio:

```bash
python3 scripts/auditoria_diaria.py
python3 setup/agendador.py instalar --hora 08:00
python3 setup/agendador.py status
```

O e-mail usa `email_from` ou `onboarding@resend.dev` e `email_aluno` da
configuração local. O envio só é considerado conferido quando a API responde
status HTTP de sucesso e devolve um identificador. Se não houver Resend, use
`--sem-email`; o canal local continua disponível. O agendador oferece a mesma
rotina em macOS, Windows e Linux, mas depende de o sistema manter o agendador
ativo.

## Leitura do relatório

Investigue crescimento de tickets, backlog antigo, erros de IA, custo próximo do
teto e aumento do uso do modelo forte. Abra o hub para validar uma amostra de
conversas e veja as candidatas antes de editar a KB. A auditoria não responde
clientes, não aprova candidatas e não altera políticas do negócio.
