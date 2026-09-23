---
name: suporte-ia
description: "Orquestrador do Setup 16 de suporte com IA. Use quando o aluno disser INICIAR SETUP, suporte com IA, continuar o suporte ou mostrar o status do suporte. Conduz as Etapas 1 a 6 e a auditoria final."
model: sonnet
effort: medium
---

# /suporte-ia — Sistema de Suporte com IA

Esta é a casca de orquestração. O método de cada trabalho está no `SKILL.md` da
respectiva etapa. Sempre comece lendo o estado e mostre a etapa atual antes de
perguntar o que o aluno quer fazer.

## Estado

Na raiz do repositório, use exatamente:

```bash
python3 skills/suporte-ia/estado.py status
python3 skills/suporte-ia/estado.py continuar
python3 skills/suporte-ia/estado.py can <etapa>
python3 skills/suporte-ia/estado.py start <etapa>
python3 skills/suporte-ia/estado.py done <etapa> <artefato>
python3 skills/suporte-ia/estado.py redo <etapa>
```

O estado fica em `~/.operacao-ia/suporte/estado.json`. A ordem é fixa: cada
Etapa exige a anterior concluída. `redo` também reabre as etapas posteriores.

## Menu

| Opção | Etapa | Ação, conferência e artefato |
|---|---|---|
| 1 | Fundação | Rode `python3 setup/setup_suporte_1_fundacao.py`. Confirme as tabelas `sup_*` via REST e o nome/descrição em `sup_config`. Marque `done 1` com o caminho do log. |
| 2 | KB inicial | Conduza `skills/suporte-kb-montar/SKILL.md`; grave com `python3 scripts/kb_importar.py --arquivo ~/.operacao-ia/suporte/kb/itens.json`. Confirme pelo `--listar` e pelo mínimo de 15 itens. Marque `done 2`. |
| 3 | Agente | Rode `python3 setup/setup_suporte_3_agente.py`. Confirme `ping` e uma mensagem de teste respondendo; marque `done 3`. |
| 4 | Hub | Rode `python3 setup/setup_suporte_4_hub.py`. Confirme o hub HTTP 200, login admin e widget acessível; marque `done 4` com a URL. |
| 5 | Aprendizado | Conduza `skills/suporte-kb-aprender/SKILL.md`. Confirme candidatas aprovadas na `sup_kb` e marcadas como aprovadas; marque `done 5` com o log. |
| 6 | Auditoria diária | Rode `python3 scripts/auditoria_diaria.py --dry-run --sem-email`; depois, com confirmação explícita do aluno, rode `python3 setup/agendador.py instalar --hora 08:00` ou a API do módulo. Confirme o relatório e `python3 setup/agendador.py status`; marque `done 6`. |
| 7 | Auditoria final | Só depois de 1–6 concluídas, rode `python3 setup/audit.py`. Confira cada linha, corrija falhas e só marque `done 7` com o relatório final. |

## Roteamento

1. Rode `status`.
2. Apresente o menu com o estado de cada Etapa.
3. Para uma escolha, rode `can <etapa>`. Se retornar bloqueio, explique qual
   Etapa falta e não execute o script seguinte.
4. Se liberada, rode `start <etapa>`, siga o método completo da skill indicada,
   confira o efeito real e só então rode `done <etapa> <artefato>`.
5. Ao terminar, rode `status` novamente. A Etapa 7 é sempre a conferência final.

Não peça chaves no chat. Quando um script precisar de segredo, ele deve usar
`getpass` ou a configuração local já existente. Não publique nem comite
`config.js` gerado.
