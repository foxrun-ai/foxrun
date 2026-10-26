---
type: doc
workspace: system
timestamp: 2026-10-19T19:35:51-04:00
---
# Wiki compile

```sh
python3 memory/compile.py --workspace /path/to/vault/foxrun --sources /path/to/saved-sources --answer /path/to/research-answer.md --as-of 2026-10-05
```

Repeat `--sources` for source folders or files. Repeat `--answer` for research answers.
All source locations come from arguments. The command uses no model or network.
Only safe Markdown sources are read. Hidden, protected, settings, archive, and symlink paths are excluded.

Topic pages group existing topic, topic_id, or tag values.
A source without those values uses its existing title.
Native wiki titles replace raw filenames when their source links match exactly.
This grouping creates no new tag rows or model rulings.
Topic pages use the native concepts/ folder and show source, who, subtopic, original, capture, and raw source.
Existing handwritten concept pages stay intact. Generated topic names end with -sources.md.
The index links topic pages, queries, other existing pages, and all sources.

Sources stay in place. The compiler writes frozen copies under raw/documents/.
The sha256 field hashes the complete original bytes after the raw frontmatter.
A changed source gets a new hash-named raw copy. Existing copies are never edited.
An existing raw source with a matching body hash is cited in place.
A mismatched hash stops the whole compile before writes.

Research answers land in wiki/queries/ and cite their raw source.
They preserve the saved answer text and source date.
Local links resolve against the original source home.
A frozen raw copy with a `source_path` resolves its links from that original home first.
Each relative link is rewritten relative to the generated query's own folder.
The rewriter puts a folder prefix before the written path. The author's spelling of the path stays.
Titles, query strings, headings, and all other bytes stay.
The path ends at the first `?` or `#` after decoding: written as itself, as an escape (`\#`), or as an entity (`&#35;`).
A percent-encoded one (`%23`) is part of the file name.
A leading `./` or `../` of the written path is folded into the prefix. A link to a folder works the same way.
A Markdown link can also start at the vault root, or leave out the `.md` of a note. Both are found and rewritten.
A link whose target does not exist stays as written. The manifest lists it with file and line.
Absolute URLs, anchors, and empty destinations stay as written.
A wikilink that names a real note becomes a Markdown link with a relative path.
The note is found the way workspace notes finds it: by path from the source's folder, by path from the vault root,
then by name anywhere in the vault, where the shortest path wins.
A target is judged as it is when the compile ends. A page this compile writes is there.
A generated page this compile archives is gone: a link to it stays as written and is reported.
A link in a source title does not reach a page heading: the heading keeps the link text only.
An answer that leaves a code block or an HTML block open gets its closing line, so the citation stays a link.
The compiler invents no relationship or fact.

## Links: one scanner, one independent check

`markdown_links.py` is the one link scanner. The rewriter and the check both use it.
It reads the block structure first: block quotes, list items, footnote definitions, fenced code, indented code, and HTML blocks.
It strips each container prefix to get the logical text, and keeps the source offset of every character.
It finds inline links and images, reference links (full, collapsed, shortcut), reference definitions
with a destination or title on following lines, angle-bracket destinations, autolinks,
`href` and `src` attributes in HTML, and wikilinks and embeds with aliases, headings, and block ids.
It skips fenced code, indented code, code spans, HTML comments, and the text of HTML blocks.
It follows CommonMark. A line that starts with an HTML comment is an HTML block to its end.
It keeps two readings of a footnote line. A vault reads `[^n]: text` as a footnote.
Plain CommonMark reads `[^n]: file.md` as a definition, and the rest of such a line as paragraph text.
A link that only the plain reading sees is moved when it names a real file. It is never reported as missing.

`link_check.py` is the check. It is not the rewriter's mirror.

```sh
python3 memory/link_check.py --workspace /path/to/vault/foxrun --workspace /path/to/vault/cedar-shop
```

It collects candidates with broad patterns over the raw text: every `](`, every `]:`, every `[[...]]`, every `href=` and `src=`.
Each candidate must end one of these ways:

- The scanner saw it as a link. The check reads the destination by its own rules and resolves it from the page's own folder.
- The scanner named it as not a link, with a reason (code, comment, refused bracket).
- Neither. That is a FAIL line. A link the scanner did not see cannot pass.

A refused candidate that names a real file on the source side is a suspect.
A suspect passes only when pandoc, an independent CommonMark parser, renders no broken link on that page.
When pandoc is installed, the check also renders every page with it, as plain CommonMark and with footnotes,
and resolves every rendered link. Without pandoc, a suspect is a FAIL line.
The compiler itself needs only Python's standard library.
A link that fails from the page and from the source side was broken in the source. It is listed. It is not a FAIL.

`link_cases.json` is the case table: each case has a source text and its exact expected output.
`test_markdown_links.py` runs it:

```sh
TMPDIR=/a/safe/folder python3 -m unittest memory/tests/test_markdown_links.py
```

Not read as links: `srcset`, `poster`, and other attributes; bare URLs with no brackets.
A destination that starts with a scheme (`name:`) or with `/` is not relative. It stays as written.

An explicit source URL supplies the original link. Otherwise, the saved source remains the locator.

The generated manifest is outputs/workspace-pages/wiki.json.
It records source paths, hashes, topic pages, and queries.
Equal sources and dates produce equal bytes. A second run changes nothing.
Older raw captures and research answer versions stay available.
Superseded generated pages move into archive/wiki-compile.
The native SCHEMA.md and log.md are preserved.

This command proves explicit research-answer routing.
Unattended skill routing, live application, and scheduling remain outside this package.
