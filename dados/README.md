# Dados brutos das medições

Todas as tentativas medidas para o livro *Claude Code enxuto* (edição 1.0, medições de 24/11/2026), inclusive as rodadas de aquecimento. Nada foi filtrado além do que era pessoal (ver [O que foi tirado](#o-que-foi-tirado)).

*English summary at the [end](#english).*

| Arquivo | O quê |
|---|---|
| `bench-2026-11-24.json` | 229 tentativas de benchmark por `claude -p`, em dois blocos (110 no primeiro, 119 no segundo), no formato de registro do `measure_task.py` |
| `sessoes-reais-2026-11-24.json` | as 2 tarefas reais da linha de base do capítulo 1, no app desktop |
| `tentativas-2026-11-24.csv` | as 231 tentativas numa tabela só, com a coluna `set` dizendo de qual arquivo veio cada uma |

## Ambiente

- **Data:** 24/11/2026.
- **Blocos:** o benchmark inteiro rodou duas vezes nesse dia, cada vez com o cache frio: o primeiro bloco de dia, com a base de notas sendo editada, e o segundo à noite, com ela parada, na mesma ordem e com as mesmas flags. As fases do segundo bloco terminam em `-b2`, e a base dele se chama `base-b2`.
- **Claude Code:** CLI 2.1.318 nos benchmarks; app desktop 2.1.330 nas sessões reais.
- **Modelos:** Opus 5.5 e Sonnet 5.5, esforço médio nos benchmarks.
- **Preços:** tabela da API de 03/11/2026, a mesma de [`measure/prices.json`](../measure/prices.json). O campo `cost` é o equivalente de API calculado por requisição; `cli_cost` é o custo que o próprio `claude -p` informou ao terminar.
- **Base:** uma vault pessoal de notas em Markdown, com dezenas de agentes, hooks e conectores. Os pedidos e as respostas não estão aqui, porque citam o conteúdo das notas; cada tarefa está descrita abaixo, e a conferência foi por regex na resposta.

## Tarefas

Todas só de leitura, com resposta conferível.

| Tarefa | O que pede |
|---|---|
| `consulta-leve` | um fato de uma linha que está no arquivo de instruções que o projeto manda ler no começo de toda tarefa |
| `varias-folhas` | um campo levantado em cinco notas da mesma pasta ("folha" é uma nota) |
| `arquivo-volumoso` | os campos obrigatórios de dois tipos de nota, num schema YAML de 1.660 linhas (cerca de 30 mil tokens) |
| `schema-e-folhas` | ler o schema inteiro e conferir o frontmatter de duas notas contra ele, em três passos fixos |
| `schema-inteiro` | a mesma tarefa, como primeira de uma sequência de três |
| `retomar-ideia` | sessão real: retomar uma ideia antiga, ler o que existia e escrever uma proposta |
| `promover-ideia` | sessão real: transformar a proposta em projeto, na mesma sessão da anterior |

## Fases

Cada fase muda uma coisa e existe nos dois blocos. As de aquecimento rodaram antes da comparação, para o cache não favorecer nenhum lado, e ficam fora da conta. A coluna de tentativas dá o primeiro bloco mais o segundo.

| Fase | O que muda | Tentativas | Capítulo |
|---|---|---:|---|
| `base-2026-11-24`, `base-b2` | configuração padrão do `claude -p`, Opus | 12 + 12 | 4 e 5 |
| `worker-enxuto` | `--setting-sources project,local --strict-mcp-config --disable-slash-commands --tools Read,Grep,Glob`, Opus | 12 + 12 | 5 |
| `worker-sem-hooks` | o mesmo, com `--setting-sources local`; uma rodada no primeiro bloco, quatro no segundo | 3 + 12 | 5 e 11 |
| `aquecimento-sonnet` | aquecimento do Sonnet no worker enxuto | 3 + 3 | 6 |
| `cmp-opus`, `cmp-sonnet` | worker enxuto, Opus contra Sonnet | (9 + 9) + (9 + 9) | 6 |
| `aquecimento-leitura` | aquecimento da leitura dirigida, nos dois modelos | 6 + 6 | 7 |
| `leitura-opus`, `leitura-sonnet` | worker enxuto com a instrução de leitura dirigida | (9 + 9) + (9 + 9) | 7 |
| `aquecimento-sub-a`, `aquecimento-sub-b` | aquecimento das duas variantes do subagente | (1 + 1) + (1 + 1) | 8 |
| `sub-principal` | a conversa principal lê o schema inteiro | 6 + 6 | 8 |
| `sub-subagente` | um subagente Explore no Sonnet lê o schema e devolve só os campos; `--tools` inclui `Agent` | 6 + 6 | 8 |
| `aquecimento-sessao-mesma`, `aquecimento-sessao-nova` | aquecimento das duas variantes de sessão | (3 + 3) + (3 + 3) | 9 |
| `sessao-mesma` | três tarefas em sequência na mesma sessão, por `--resume` | 9 + 9 | 9 |
| `sessao-nova` | as mesmas três tarefas, cada uma numa sessão nova | 9 + 9 | 9 |
| `antes` | as duas sessões reais da linha de base | 2 | 1 |

## Campos

O JSON segue o formato de registro do `measure_task.py`: `{"version": 1, "attempts": [...]}`, uma entrada por tentativa.

- `session`: id anônimo da sessão (`b001`, `r001`...). Nas fases de sessão mesma, as três tarefas de uma rodada continuam a mesma sessão por `--resume` e têm o mesmo id; `resumed_from` diz de qual tarefa a sessão foi continuada.
- `task`, `phase`, `completed`: a tarefa, a fase e se o regex conferiu a resposta.
- `since`, `until`: a janela de tempo medida, quando a tentativa é só um pedaço da sessão.
- `run`: modelo, esforço, flags passadas ao `claude` (`extra`), segundos, turnos, custo informado pelo CLI e o número da repetição dentro de uma chamada do benchmark (`attempt`, que só passa de 1 com `--repeat`). As rodadas se distinguem pela ordem no arquivo e pelo horário de início: a rodada fria da base, por exemplo, são as três primeiras tentativas da fase.
- `measurement`: requisições, tokens por classe (`input`, `cache_write_5m`, `cache_write_1h`, `cache_read`, `output`), custo total e por classe em US$, contexto da primeira requisição e o maior contexto da sessão, início e fim.

O CSV tem as mesmas colunas, achatadas, com nomes em inglês.

## Reproduzir um número do livro

O `compare` lê o JSON direto e junta fases separadas por vírgula. O worker enxuto do capítulo 5, nos dois blocos:

```bash
python measure/measure_task.py compare --registry dados/bench-2026-11-24.json \
  --before base-2026-11-24,base-b2 --after worker-enxuto,worker-enxuto-b2
```

O custo por tarefa concluída vai de US$ 0,160 para 0,113 (−29%), e a mediana por tentativa fica empatada (0,106 e 0,104). Só o primeiro bloco (`--before base-2026-11-24 --after worker-enxuto`) dá −37% e −53%, os números da edição 0.9; o capítulo 10 do livro explica a diferença. Passe sempre `--before` e `--after`: sem eles, o `compare` pega as duas primeiras fases do arquivo.

## O que foi tirado

- os ids reais de sessão, trocados por ids anônimos;
- os pedidos, as respostas e as anotações, que citam o conteúdo das notas;
- o texto da instrução de leitura dirigida dentro de `extra`, trocado por uma marcação; o texto está no capítulo 7 do livro;
- os nomes de duas tarefas reais, trocados por nomes genéricos.

Nenhum número foi mexido: o script que gera esta pasta confere, fase a fase, que o `compare` dá o mesmo resultado nos dados originais e nos limpos.

## Limites

São medições de um dia, numa base só, com tarefas só de leitura e resposta conferível por regex. Nem todas as fases foram intercaladas entre si: no primeiro bloco, o controle da leitura dirigida são as fases `cmp-opus` e `cmp-sonnet`, rodadas antes dela; no segundo, as quatro se alternaram rodada a rodada. Cada capítulo diz o que foi intercalado com o quê. Uma versão nova do Claude Code ou uma tabela de preços nova muda os números; o método do capítulo 10 continua valendo.

Licença: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.pt-br).

## English

Raw data behind *Claude Code enxuto*, edition 1.0, measured on 24/11/2026: 229 benchmark attempts run with `claude -p` (CLI 2.1.318) in two blocks on the same day (second-block phases end in `-b2`) and the 2 real desktop-app sessions (2.1.330) from chapter 1, Opus 5.5 and Sonnet 5.5 at medium effort, API-equivalent cost with the 03/11/2026 price table. The JSON files use the `measure_task.py` registry format, so `compare --registry dados/bench-2026-11-24.json --before base-2026-11-24,base-b2 --after worker-enxuto,worker-enxuto-b2` reproduces the chapter 5 result (cost per completed task −29%, median per attempt tied); the first block alone gives the 0.9 edition's −37% and −53%. The CSV has the same fields with English column names. Session ids are anonymous; prompts, answers and notes were removed because they quote a personal notes vault; no number was changed. License: CC BY 4.0.
