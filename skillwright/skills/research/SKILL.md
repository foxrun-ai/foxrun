---
name: research
description: "Research one question with fetched, numbered sources: quick (one reader on primary sources, the default), deep (the research workflow), or docs (library and repo docs). Use when the person says /research, research this, look into, find out, or what do the docs say."
kind: tool, knowledge
---

# research

Answer one question from sources you fetched, never from memory.
Every claim from a source carries a number, such as `[2]`.
The numbers come from the citation ledger, `bin/sources.py`, so a number always points at a page you read.

## Steps

1. Pick the mode from the person's words:

   | Mode | When | Engine |
   |---|---|---|
   | `quick` (default) | One question, one sitting | You, on primary sources, with the `/read` engines |
   | `deep` | `/research deep`, or a question with many sides and real stakes | The flow `research` workflow: three researchers, then a writer |
   | `docs` | `/research docs`, or a question about a library, an API, or a repo | `ctx7`, DeepWiki, and the repo through `gh` |

   Recent social talk (`/research pulse`) is not this skill. Use `last30days`, or `x-research` for X.
   Done when you have one mode and the question in neutral words.

2. Start a clean ledger for this question:

   ```sh
   R="${FOXRUN_HOME:-$HOME/.foxrun}/skills/research"
   export FOXRUN_CITATION_LEDGER="$(mktemp -d)/ledger.json"
   python3 "$R/bin/sources.py" reset
   ```

   Done when it prints `ledger reset:` and the path.

3. Fetch the sources for the mode.

   - `quick`: find the primary source that owns each fact: the official page, the spec, the code, the first-party data. Read each one with the `read` skill and save its text to the ledger folder.
   - `docs`: `ctx7 library <name> "<question>"` gives a library id, then `ctx7 docs <id> "<question>"` gives the docs. For a GitHub repo, ask DeepWiki (`ask_wiki_question` on the DeepWiki MCP), and read the files with `gh api repos/<owner>/<repo>/contents/<path>` or `gh search code`.
   - `deep`: run `python3 "${FOXRUN_HOME:-$HOME/.foxrun}/work/flow.py" run research --input question="<question>"` as a background task. Follow the `flow` skill until the run is `done`, then take its `answer.md` to step 5.

   After each fetch, register the URL right away: `python3 "$R/bin/sources.py" add <url> --title "<title>"`. It prints the number.
   Done when every source you will cite has a number from `add`.

4. Attach the exact words for each claim that carries the answer:

   ```sh
   python3 "$R/bin/sources.py" quote <n> --text "<words copied from the page>" --from <saved page text>
   ```

   The ledger refuses a quote that is not in the fetched text. Copy the words; never retype them.
   Done when each cited source has at least one quote.

5. Write the answer in a draft file in the ledger folder.
   Put the number right after the sentence it supports, such as `Ice floats.[1]`. Use at most three numbers on a sentence.
   A claim you could not source gets `[unverified]`, not a number.
   Then add the source list: `python3 "$R/bin/sources.py" render --style evidence --replace-in <draft>`.
   Done when the draft ends with a `## Sources` block that the script wrote.

6. Check it: `python3 "$R/bin/sources.py" verify <draft> --evidence`.
   Done when it prints `citations OK`. On `FAIL`, fix the draft or fetch the missing source, then check again.

7. Give the person the answer with its numbered sources.
   Save a file only when the person asks. A kept answer goes to `<ws>/wiki/queries/`.
   Done when the person has the answer and every number resolves to a fetched page.

## Gotchas

- Register a source when you fetch it, not after you write. A number added from memory defeats the ledger.
- Never edit numbers or the source list by hand. Use `render --replace-in`.
- A search result snippet is not the page. Read the page before you cite it.
- A Reddit thread or a post shows what people report, not what is true. Pair it with a primary source, or label it as opinion.
- A copy from `capture-recover` is an archived snapshot. Cite it with its date.
- `deep` starts several agents and takes up to 30 minutes. Say so before you start it.
- Parallel helpers that feed one answer share one ledger: pass each the same `FOXRUN_CITATION_LEDGER`.
- `bin/sources.py` is ported from Hermes Agent's grounded-citations skill under the MIT License. Its header holds the notice.
