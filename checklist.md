# Checklist: gastar menos com o Claude Code, medindo

Uma página. Cada item traz o número que eu medi e o capítulo do livro *Claude Code enxuto* com o método e os casos em que ele não vale; o capítulo 1 está [neste repositório](capitulo-1.md). Medições de 24/11/2026, com o benchmark rodado em dois blocos no mesmo dia, Opus 5.5 e Sonnet 5.5, em equivalente de API. O seu número vai ser outro: meça antes e depois.

Não some os percentuais. Eles se sobrepõem: depois que um item cortou as leituras inteiras, sobra menos para o seguinte.

## Antes de mudar qualquer coisa

- [ ] **Meça a linha de base.** Três tarefas que você faz toda semana, cada uma registrada com `measure_task.py record --phase antes`. A minha ficou em US$ 1,81 por tarefa concluída no app desktop, com 20 requisições por tarefa. (cap. 1)
- [ ] **Veja qual classe pesa mais.** Se for a gravação de cache de 1 hora, como foi aqui (36% a 44% do custo), o problema é o que entra na conversa, não o tamanho da resposta. (cap. 1)

## Em ordem de ganho por esforço

- [ ] **Leitura dirigida.** Uma instrução de três frases para o modelo buscar o trecho antes de abrir o arquivo inteiro. −47% no custo por tarefa no Sonnet e −36% no Opus, 36 tentativas em dois blocos, todas concluídas. No Opus, ela tira a cauda cara das leituras inteiras. Piorou em tarefa minúscula: +35%, por uma requisição a mais, nos dois blocos. (cap. 7)
- [ ] **Worker enxuto em todo `claude -p`.** `--setting-sources project,local --strict-mcp-config --disable-slash-commands` e, em `--tools`, só as ferramentas do papel. −29% no custo por tarefa, 24 tentativas por lado, com a mediana empatada: o ganho está no cache frio (−47% e −50%) e no arquivo grande. A abertura foi de 42,8 mil para 12,4 mil tokens. Junto com a leitura dirigida, −58%. Trocar `project,local` por `local` corta mais, mas leva junto as regras do projeto. (cap. 5)
- [ ] **Sonnet nas tarefas leves.** Cerca de 50% mais barato que o Opus nas tarefas leves, com todas as respostas certas. No arquivo grande, saiu 32% mais caro até a leitura dirigida entrar; por isso este item vem depois dela. (cap. 6)
- [ ] **Subagente Sonnet para a leitura pesada inevitável.** −48% numa tarefa de vários passos, quase o mesmo nos dois blocos, e o maior contexto da conversa principal caiu 55%. Não vale quando a principal precisa do conteúdo intermediário para decidir. (cap. 8)
- [ ] **Continue a sessão dentro da janela do cache.** Seguir na mesma sessão saiu 79% mais barato na consulta seguinte e 36% na tarefa de várias notas. Abra uma nova quando o histórico não servir para a próxima tarefa ou o cache já tiver vencido. (cap. 9)
- [ ] **Enxugue a abertura.** Descrições curtas de agente, índice de memória enxuto e plugins sem uso desligados: −5,2 mil tokens por abertura, uns US$ 0,06 por tarefa. Pouco, mas vale para toda sessão. (cap. 3)
- [ ] **Automação no CLI, não no app.** A primeira requisição pesou 92,7 mil tokens no app desktop e 47,3 mil no CLI, na mesma pasta. (cap. 2)

## O que rendeu menos que a fama (cap. 11)

- **Resposta curta:** a saída foi de 23% a 28% do custo nas tarefas reais. Cortar metade dela economizaria menos de 14%.
- **`/clear` por hábito:** dentro da janela do cache, continuar saiu mais barato. O custo de uma sessão nova é o que a próxima tarefa vai precisar reler.
- **Trocar de modelo antes de mudar a leitura:** o Sonnet lendo arquivos inteiros saiu 32% mais caro que o Opus no arquivo grande.
- **Worker enxuto com o cache quente:** a mediana empatou com a configuração padrão. A abertura menor vale pouco quando o modelo abre o arquivo inteiro.

## Como conferir cada item (cap. 10)

- [ ] Uma mudança por vez, sempre contra a mesma base.
- [ ] Uma rodada de aquecimento fora da conta: a mesma tarefa repetida caiu de US$ 0,26 para 0,05 sem mudar a configuração, só por causa do cache.
- [ ] Nada muda na abertura enquanto mede: arquivos de instruções, memória e saída de hooks parados. Uma edição no meio inflou a minha linha de base.
- [ ] Fases intercaladas, rodada a rodada, e a mediana no lugar do total.
- [ ] A tentativa que falhou entra na conta: o `compare` divide o custo de todas as tentativas pelas concluídas.
- [ ] Olhe tarefa por tarefa: uma média boa esconde a tarefa que piorou.
- [ ] Antes de adotar para tudo, repita o bloco inteiro em outro horário. O −53% da edição 0.9 não se repetiu. (cap. 10)

---

*Claude Code enxuto*, edição 1.0. Texto sob [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/deed.pt-br).
