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
