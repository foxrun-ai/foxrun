# Published pages

Run from the system home:

```sh
python3 -B base/published_pages.py --home "$FOXRUN_HOME" --portfolio "$FOXRUN_PORTFOLIO"
python3 -B base/published_pages.py --home "$FOXRUN_HOME" --portfolio "$FOXRUN_PORTFOLIO" --check
```

Set both variables to the two installed folders before these commands.
Shared words live as TSV rows in `base/published/words.tsv`.
Local words live in `<workspace>/config/glossary-words.tsv` with the same four-column header.
The columns are `word`, `meaning`, `group`, and `source`.
A local page contains only local words and a link to the shared page.
The person approves tags. The keeper maintains their exact list and instructions in `config/glossary-tags.json`.
The eight current local pages contain no business words; no words were invented.
`GUIDE.md` and `INSTALL.md` are hand-written product pages. The generator does not build or check them.
A linked workspace folder is skipped; its real folder gets the page.
It never writes agent start pages.
The installer regenerates the glossary pages after database creation.
No timed stranger read is recorded yet. Do not claim ten-minute acceptance.
This TSV word store does not migrate the dictionary or rename storage columns.
A future database-backed words table needs its own schema and import review.

The shared refresh job owns product-manifest.tsv and made-at-install.tsv.
After that refresh, regenerate these human pages from the final install rows.
