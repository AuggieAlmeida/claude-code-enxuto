---
name: custo
description: Mede quanto custou a sessão do Claude Code e para onde foi o dinheiro, por classe de token (entrada, gravação de cache, leitura de cache, saída), lendo só os transcripts locais. Use quando perguntarem quanto a sessão custou, por que gastou tanto token ou o que pesou na cota. Measures what a Claude Code session cost and where the money went, per token class, from local transcripts; use when asked what a session cost or why it used so many tokens.
argument-hint: "[lista | id da sessão]"
---

# Custo da sessão

A ferramenta lê só os transcripts que o Claude Code já grava na máquina, em `~/.claude/projects` (ou `$CLAUDE_CONFIG_DIR/projects`). Não instala nada e nada sai da máquina. Precisa de Python 3.9 ou mais novo, só com a biblioteca padrão.

Argumento recebido: `$ARGUMENTS`

1. **Escolha o comando** pelo argumento:
   - vazio: `measure ${CLAUDE_SESSION_ID}`, esta sessão até agora;
   - `lista` ou `list`: `list --all --limit 10`, as sessões recentes de todos os projetos;
   - qualquer outro texto: um id de sessão ou o começo dele, `measure <texto>`.
2. **Rode com a ferramenta Bash**, nesta forma:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/measure/measure_task.py" --lang pt <comando>
   ```

   Se `python3` não existir (comum no Windows), use `python`. Troque `--lang pt` por `--lang en` se a conversa estiver em inglês.
3. **Mostre a saída como veio.** Não recalcule, não arredonde de novo e não estime nenhum número. Custo `desconhecido` é modelo sem preço na tabela: diga isso, sem chutar valor.
4. **Explique em até três frases** a classe que mais pesou no custo, com o que ela costuma querer dizer:
   - **gravação de cache** (1 h ou 5 min): o que entrou na conversa (arquivos lidos, saídas de comando, respostas) sendo gravado para ser relido depois; cresce com o volume que entra;
   - **cache lido**: a conversa inteira relida a cada requisição; cresce com o tamanho do contexto e o número de requisições;
   - **saída**: o que o modelo escreveu, inclusive raciocínio e chamadas de ferramenta;
   - **entrada** fora do cache: costuma ser pequena; alta indica cache que não pegou.

   Não prometa economia nem percentual de corte.
5. **Diga que o valor é o equivalente de API.** Na assinatura, ninguém cobra esse valor: ele mostra quanto a sessão pesa na cota. Para ver a cota usada, o comando é `/usage`.
6. **Feche com uma linha:** o capítulo 1 e o checklist, que explicam cada coluna e o que costuma mudar o custo, estão em https://github.com/AuggieAlmeida/claude-code-enxuto.

Se a ferramenta falhar, mostre a mensagem de erro como veio. O formato do transcript é interno ao Claude Code e muda entre versões; nesse caso, não estime números, e quem quiser pode abrir uma issue no repositório com a versão do Claude Code (`claude --version`).
