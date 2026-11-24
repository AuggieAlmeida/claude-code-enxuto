# 1. Medir antes de mexer

> Capítulo 1 de *Claude Code enxuto*, edição 0.9. A ferramenta deste capítulo está em [`measure/`](measure/), e os dados das medições, em [`dados/`](dados/). Sobre o livro: [README](README.md#o-livro). Texto sob [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/deed.pt-br).

Antes de medir, eu achava que o caro no Claude Code era a resposta: o modelo escrevendo código, explicando, pensando. A primeira medição desmentiu isso. Numa tarefa comum, a resposta era menos de um terço da conta. A maior parte ia para uma linha que eu nem sabia ler: gravação de cache de uma hora.

Esse é o motivo deste capítulo vir primeiro. Quase toda dica de economia de tokens que circula por aí ataca o lugar errado, porque ninguém mediu onde o dinheiro vai. Aqui você vai medir a sua conta antes de mudar qualquer coisa, com uma ferramenta que roda na sua máquina e lê o que o Claude Code já anota sozinho.

## O que o Claude Code já anota por você

Cada sessão do Claude Code vira um arquivo de transcript em `~/.claude/projects/`, numa pasta com o nome do projeto (o caminho da pasta, com os separadores trocados por hífen). O arquivo da sessão tem uma linha por evento: o seu pedido, cada resposta do modelo, cada chamada de ferramenta. Os subagentes ganham arquivos próprios, numa subpasta `subagents/` com o mesmo nome da sessão.

Toda resposta do modelo traz um bloco `usage` com quantos tokens a requisição consumiu, separados por classe. É o mesmo número que a API cobra. A ferramenta deste capítulo só faz três coisas com isso: junta a conversa principal com os subagentes, conta cada requisição uma vez (o transcript às vezes repete a mesma resposta em mais de uma linha) e multiplica cada classe pelo preço dela.

## As cinco classes de token

O que a API cobra numa requisição não é um número só. São cinco, cada um com seu preço:

| Classe | O que é | Opus 5.5 (US$ por milhão) | Sonnet 5.5 (US$ por milhão) |
|---|---|---|---|
| Entrada | o que vai na requisição e não veio do cache | 4,00 | 2,00 |
| Gravação de cache, 5 minutos | entrada guardada no cache por 5 minutos (1,25x a entrada) | 5,00 | 2,50 |
| Gravação de cache, 1 hora | entrada guardada no cache por 1 hora (2x a entrada) | 8,00 | 4,00 |
| Leitura de cache | entrada que já estava no cache (0,05x a entrada nesses dois modelos) | 0,20 | 0,10 |
| Saída | o que o modelo escreve, incluindo o raciocínio | 20,00 | 10,00 |

Preços da API em 03/11/2026. Confira os atuais antes de usar os seus números; eles ficam no arquivo [`measure/prices.json`](measure/prices.json) deste repositório, e um modelo sem preço na tabela aparece como "desconhecido", nunca estimado.

Guarde a diferença entre as linhas do meio. Ler do cache custa 40 vezes menos que gravar no cache de uma hora. O resto do livro gira em torno disso.

Se você já leu que a leitura de cache custa 10% da entrada, não está errado: era assim em vários modelos anteriores e continua assim em alguns deles. A proporção muda de modelo para modelo: no Opus 5.5 e no Sonnet 5.5 a leitura caiu para 5%, e no Fable 5.1 e 5.2 é 2,5%, e o próprio blog da Anthropic usa esse número ao comparar o Opus 5.5 com o Opus 5. Por isso o `prices.json` guarda o preço de leitura de cada modelo em vez de aplicar um multiplicador único.

## Rodando a medição

A ferramenta não instala nada: é Python 3.9 ou mais novo, só com a biblioteca padrão. De dentro da pasta do seu projeto:

```bash
python measure/measure_task.py list
```

O `list` mostra as sessões recentes do projeto da pasta atual, com início, duração, número de requisições, custo e título. O título é o que você deu à sessão ou, na falta dele, o seu último pedido. Para ver todos os projetos, use `--all`.

Escolha uma sessão e meça. Basta o começo do id, como no git:

```bash
python measure/measure_task.py measure e0bdeada
```

Se a sessão teve mais de uma tarefa, recorte pela hora com `--since` e `--until`. Hora sem fuso é lida como hora local:

```bash
python measure/measure_task.py measure e0bdeada --until 2026-11-24T03:08
```

A saída sai em português; `--lang en` troca para inglês.

## Lendo o resultado

Esta foi a primeira tarefa que eu medi: retomar uma ideia antiga na minha vault de notas, ler o que existia e escrever uma proposta. Seis minutos, Opus 5.5, no app desktop do Claude Code.

| Modelo | Requisições | Entrada | Cache grav. 5 min | Cache grav. 1 h | Cache lido | Saída | Custo (US$) |
|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | 20 | 40 | 0 | 88.776 | 2.319.684 | 22.765 | 1,63 |

- Custo por classe: entrada 0% · gravação de 5 min 0% · gravação de 1 h 43,6% · leitura de cache 28,5% · saída 27,9%
- Leitura de cache: 96,3%
- Contexto na primeira requisição: 92.678 · maior contexto: 137.920 · contexto médio: 120.425

Vale fazer a conta à mão uma vez, para confiar na ferramenta:

- gravação de 1 hora: 88.776 tokens × US$ 8 por milhão = US$ 0,71;
- leitura de cache: 2.319.684 × US$ 0,20 por milhão = US$ 0,46;
- saída: 22.765 × US$ 20 por milhão = US$ 0,46.

Total: US$ 1,63. Cada linha do resultado responde uma pergunta.

**Requisições.** Cada vez que o Claude Code chama o modelo conta uma: o seu pedido, e cada volta depois de uma ferramenta. Vinte requisições numa tarefa de seis minutos é normal. É também por isso que o contexto pesa: ele vai inteiro em cada uma das vinte.

**Cache lido: 2,3 milhões de tokens.** Parece absurdo para uma conversa curta, mas é só 20 vezes um contexto de cerca de 116 mil. O Claude Code manda a conversa inteira em toda requisição; o cache só faz esse reenvio custar 0,05x. É barato por token e caro no volume.

**Gravação de cache de 1 hora: a maior classe.** Tudo o que entra pela primeira vez na conversa principal, como um arquivo lido, a saída de um comando ou a resposta do modelo, é gravado no cache de uma hora a 2x o preço de entrada, para ser relido barato depois. Foi assim no app e no CLI, nas versões medidas; os subagentes usaram o cache de 5 minutos. Foram 89 mil tokens gravados, 44% do custo. É aqui que estão as maiores alavancas do livro.

**Saída: menos de um terço.** A parte que eu achava cara.

**Contexto na primeira requisição: 92.678 tokens.** Isso foi enviado antes de qualquer trabalho: instruções do sistema, definições de ferramentas, listas de agentes e skills, arquivos de instruções do projeto, memória. O capítulo 2 desmonta esse número bloco a bloco.

**Conversa principal e subagentes.** O resultado traz uma segunda tabela com essa divisão. Aqui não houve subagente. Quando houver, você vê quanto cada lado custou e em qual modelo.

## A unidade que importa: custo por tarefa concluída

Uma sessão medida é um retrato. Para comparar antes e depois, você precisa de uma unidade, e a unidade certa não é token nem sessão: é tarefa concluída. Uma configuração que deixa cada tentativa 30% mais barata, mas precisa de duas tentativas para acertar, ficou mais cara.

O `record` guarda cada tentativa num arquivo de registro, com o nome da tarefa, a fase e se ela foi concluída:

```bash
python measure/measure_task.py record e0bdeada --until 2026-11-24T03:08 \
  --task retomar-ideia --phase antes --completed yes --registry medicoes.json
```

Registre também as tentativas que falharam, com `--completed no`. O `compare` divide o custo de todas as tentativas da fase pelo número de tentativas concluídas, de modo que a tentativa que deu errado pesa na conta da que deu certo:

```bash
python measure/measure_task.py compare --registry medicoes.json
```

Com duas tarefas medidas, a minha linha de base ficou em **US$ 1,81 por tarefa concluída**, com 20 requisições por tarefa e 95% da entrada lida do cache.

A segunda tarefa trouxe outro achado. Eu a fiz na mesma sessão, logo depois da primeira, e ela já começou com 141 mil tokens de contexto, herdando tudo da anterior. A conclusão óbvia seria "abra uma sessão nova entre tarefas". O capítulo 9 mede isso, e a resposta não é a óbvia.

## Cuidados com os números

**Equivalente de API não é a sua fatura.** Se você usa o Claude Code pela assinatura, ninguém cobra US$ 1,81 por tarefa: você sente o custo quando bate no limite da janela de 5 horas ou no limite semanal. Para ver quanto da cota já foi, use as barras do `/usage`, que também mostram quais skills, subagentes e servidores MCP mais consumiram. Para comparar uma configuração com outra, tarefa por tarefa, use o equivalente de API deste capítulo: ele é a mesma régua em qualquer plano, e é o preço real para quem usa a API.

**Preço muda.** O arquivo `prices.json` tem a data em que foi conferido. Atualize antes de publicar ou comparar números de meses diferentes.

**Transcripts somem.** O Claude Code apaga transcripts antigos depois de um prazo configurável (`cleanupPeriodDays`). O `record` guarda a medição dentro do registro justamente para a comparação não depender dos arquivos originais.

**A mesma tarefa repetida fica mais barata.** Dentro de uma hora, uma abertura idêntica já está no cache. No meu teste, a mesma tarefa caiu de US$ 0,26 para US$ 0,05 em quatro repetições. Se você medir o "antes" com cache frio e o "depois" com cache quente, vai encontrar uma economia que não existe. O capítulo 4 explica o mecanismo e o capítulo 10, como fugir dele.

**Uma sessão, várias tarefas.** Recorte com `--since` e `--until`; senão, o registro mistura tarefas diferentes.

## Exercício

1. Rode `list` no projeto onde você mais usa o Claude Code.
2. Meça as três últimas sessões com `measure`.
3. Em cada uma, ache a classe que mais pesa no custo por classe. Se for a gravação de cache de 1 hora, como no meu caso, anote o contexto na primeira requisição.
4. Escolha três tarefas que você faz toda semana e registre a próxima execução de cada uma com `record --phase antes`. Essa é a sua linha de base: todo capítulo daqui em diante vai mexer em alguma coisa e você vai comparar com ela.

No próximo capítulo, o número que mais me surpreendeu: o que vai naqueles 92.678 tokens que o modelo lê antes de você pedir qualquer coisa.

---

*Claude Code enxuto* tem mais onze capítulos: a abertura bloco a bloco, o cache, o worker enxuto, modelo, leitura, subagente, sessão, benchmark honesto, o que não rende e a receita. Veja o [README](README.md#o-livro).
