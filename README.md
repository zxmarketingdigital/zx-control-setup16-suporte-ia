# Setup 16 — Sistema de Suporte com IA

Este é um sistema instalável pelo próprio negócio para organizar atendimento no
WhatsApp e no site. Ele combina respostas baseadas em uma base de conhecimento,
encaminhamento para uma pessoa, hub de tickets com login, aprendizado mediante
aprovação e auditoria diária.

Serve para qualquer nicho: comércio, serviços profissionais, educação, saúde,
eventos, criadores, negócios locais e operações digitais. O conteúdo da base é
definido pelo aluno; o sistema não inventa políticas do negócio.

## Pré-requisitos

- Setups 1 e 2 concluídos, com Python 3.9 ou mais recente compatível, Git e
  `~/.operacao-ia/config/config.json` criado.
- Conta Supabase própria, Supabase CLI, Node/npx e Wrangler disponíveis.
- Evolution configurada para habilitar WhatsApp. Ela é opcional para testar
  somente o site.
- Resend configurado para receber a auditoria por e-mail. Sem Resend, use o
  relatório local e `--sem-email`.
- Um repositório público acessível ao aluno e um terminal com Claude Code.

## Instalação guiada

```bash
gh repo clone zxmarketingdigital/zx-control-setup16-suporte-ia && cd zx-control-setup16-suporte-ia && claude
```

No Claude Code, digite:

```text
INICIAR SETUP
```

O comando abre `/suporte-ia`, mostra o estado e conduz as etapas na ordem.

## As etapas

1. Fundação: configura as tabelas, políticas e dados iniciais do Supabase.
2. Base de conhecimento: entrevista o aluno e importa pelo menos 15 respostas
   confirmadas.
3. Agente: configura o provedor, a cascata de atendimento e o webhook.
4. Hub: publica o hub de tickets, cria o primeiro membro e prepara o widget.
5. Base que aprende: revisa dúvidas recorrentes e aprova novas respostas.
6. Auditoria diária: gera métricas, relatório HTML e agendamento.
7. Auditoria técnica final: confere tabelas, segurança, função, hub, widget,
   base, agendamento e integração configurada.

## Comandos pós-instalação

```bash
python3 skills/suporte-ia/estado.py status
python3 scripts/auditoria_diaria.py --dry-run --sem-email
python3 setup/agendador.py status
python3 setup/audit.py
```

Para conferir uma janela maior:

```bash
python3 scripts/auditoria_diaria.py --dias 7 --dry-run --sem-email
```

Depois de revisar o relatório, o aluno pode configurar o horário padrão:

```bash
python3 setup/agendador.py instalar --hora 08:00
```

## Limitações e cuidados

O aluno precisa manter suas contas, chaves e serviços acessíveis. A integração
com Evolution depende de uma instância válida; sem ela, o canal site continua
sendo o caminho de teste. O widget chama a Edge Function, não o banco
diretamente. O hub é uma aplicação estática e exige conexão com Supabase Auth.

`--dry-run` e `--sem-email` nunca enviam auditoria. O sistema não substitui uma
decisão humana sobre política, reembolso, prazo ou resposta que não tenha sido
confirmada. O agendador depende do serviço de tarefas do sistema operacional e
de o computador ou servidor permanecer disponível no horário.
