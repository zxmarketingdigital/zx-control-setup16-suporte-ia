# Instruções do Setup 16 — Suporte com IA

Este repositório é instalado pelo aluno no próprio ambiente. Quando o aluno
escrever ou disser **INICIAR SETUP**, leia o estado e execute `/suporte-ia`.
Conduza uma Etapa por vez, conferindo o efeito real antes de avançar.

## Regras de atendimento

- Fale sempre em português do Brasil e use a palavra **Etapa**.
- Nunca peça uma chave, token ou senha diretamente no chat se houver um script
  que possa usar `getpass`; oriente o aluno a executar o script localmente.
- Nunca comite `config.js`, arquivos de configuração gerados ou qualquer chave.
- Não invente respostas para o negócio do aluno. Informações de produtos,
  serviços, prazos, políticas e canais precisam ser confirmadas por ele.
- Para envio externo, mostre o que será feito e aguarde confirmação quando o
  método da Etapa pedir isso.

## Fluxo

Use `python3 skills/suporte-ia/estado.py status` no início e após cada Etapa.
Os scripts são executados a partir da raiz do repositório. Se houver falha,
explique a conferência que faltou e mantenha a Etapa em andamento; não marque
como concluída só porque um comando terminou sem erro.

As skills em `skills/` são autocontidas. Leia a skill da Etapa antes de conduzir
o trabalho e não suponha que exista uma skill privada fora do repositório.

## Depois da Etapa 7: operação do dia a dia

`suporte-rotina-diaria` não é uma Etapa — é a skill que o aluno chama todo dia
(ou agenda com `/schedule`) depois que o setup termina. Ela lê
`setup/rotina_suporte.py coletar`, redige resposta para cada ticket aberto
usando só a KB e o que o cliente já disse, pede aprovação do aluno na
conversa, grava com `rotina_suporte.py responder` e entrega texto + link de
WhatsApp prontos — o envio ao cliente continua manual, pelo WhatsApp do
negócio. As candidatas de `sup_kb_candidatas` também são aprovadas
(`aprovar-kb`) ou descartadas (`descartar-kb`) ali, em vez do hub. Ela
complementa `suporte-auditoria` (Etapa 6), que só mede e nunca responde nem
aprova nada.
