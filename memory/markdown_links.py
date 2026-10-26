"""Find every link in a Markdown body, with its exact source span.

One block-aware scanner serves the rewriter and the link check.
It reads the block structure first: block quotes, list items, footnote definitions,
fenced code, indented code, and HTML blocks. It strips each container prefix to get
the logical text of a paragraph, and it keeps the source offset of every character.
It then reads the links in that logical text. Each link carries its source span,
so the rewriter changes only the path of a destination and no other byte.

The scanner also records what is not a link, and why: code, comments, HTML block text,
and each bracket it refused. The link check uses those reasons. See link_check.py.
"""

from __future__ import annotations
from dataclasses import dataclass
import html
import re
from urllib.parse import quote

PUNCTUATION = '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'
ENTITY = r'&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});'
ESCAPE_OR_ENTITY = re.compile(r'\\([!-/:-@\[-`{-~])|' + ENTITY)
ENTITY_ONLY = re.compile(ENTITY)
LINE_END = re.compile(r'\r\n|\n|\r')
THEMATIC = re.compile(r'([-*_])[ \t]*(?:\1[ \t]*){2,}$')
ATX = re.compile(r'#{1,6}(?:[ \t]+|$)')
FENCE = re.compile(r'(`{3,})([^`]*)$|(~{3,})(.*)$')
BULLET = re.compile(r'([-+*])(?=[ \t]|$)')
ORDERED = re.compile(r'(\d{1,9})([.)])(?=[ \t]|$)')
FOOTNOTE = re.compile(r'\[\^[^\]\s]+\]:')
SETEXT = re.compile(r'(?:=+|-+)[ \t]*$')
TASK = re.compile(r'\[[ xX]\](?=[ \t]|$)')
CALLOUT = re.compile(r'\[![A-Za-z][A-Za-z0-9_-]*\][+-]?')
HTML_LITERAL = re.compile(r'<(?:pre|script|style|textarea)(?:[\s>]|$)', re.I)
HTML_LITERAL_END = re.compile(r'</(?:pre|script|style|textarea)>', re.I)
HTML_NAMES = ('address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|'
              'fieldset|figcaption|figure|footer|form|frame|frameset|h1|h2|h3|h4|h5|h6|head|header|hr|html|iframe|legend|li|link|'
              'main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|'
              'title|tr|track|ul')
HTML_NAMED = re.compile(r'</?(?:' + HTML_NAMES + r')(?:[\s>]|/>|$)', re.I)
ATTRIBUTE = r'(?:\s+[A-Za-z_:][A-Za-z0-9_.:-]*(?:\s*=\s*(?:[^\s"\'=<>`]+|\'[^\']*\'|"[^"]*"))?)'
OPEN_TAG = r'<[A-Za-z][A-Za-z0-9-]*' + ATTRIBUTE + r'*\s*/?>'
CLOSE_TAG = r'</[A-Za-z][A-Za-z0-9-]*\s*>'
COMMENT = r'<!-->|<!--->|<!--[\s\S]*?-->'
HTML_COMPLETE = re.compile(r'(?:' + OPEN_TAG + '|' + CLOSE_TAG + r')[ \t]*$')
HTML_INLINE = re.compile('(' + COMMENT + r')|<\?[\s\S]*?\?>|<!\[CDATA\[[\s\S]*?\]\]>|<![A-Za-z][^>]*>|' + CLOSE_TAG + '|(' + OPEN_TAG + ')')
HTML_BLOCK_PART = re.compile('(' + COMMENT + '|<!--[\\s\\S]*$)|(' + OPEN_TAG + ')')
AUTOLINK = re.compile(r'<([A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*|[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)>')
ATTRIBUTE_LINK = re.compile(r'(?:href|src)\s*=\s*(?:"([^"\n]*)"|\'([^\'\n]*)\'|([^\s"\'<>]+))', re.I)
WIKILINK = re.compile(r'\[\[([^\[\]\r\n]*)\]\]')
SCHEME = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*:')


@dataclass
class Link:
    kind: str            # inline, image, definition, html, wikilink, embed, autolink, reference
    start: int           # the whole construct in the source
    end: int
    line: int            # the source line of the destination, or of the link when it has none
    dest_start: int = -1  # the destination text, without angle brackets or quotes
    dest_end: int = -1
    raw: str = ''        # the destination exactly as written
    label: str = ''      # link text, wikilink alias, or reference label
    key: str = ''        # normalized reference label
    defined: bool = True  # False for a full reference with no definition; that is plain text
    alternate: bool = False  # True for a link that only the plain CommonMark reading of a footnote sees

    @property
    def syntax(self):
        return 'wiki' if self.kind in ('wikilink', 'embed') else 'html' if self.kind == 'html' else 'markdown'


def decode(value, syntax='markdown'):
    """Return a destination as a reader resolves it, before percent decoding."""
    if syntax == 'wiki':
        return value
    if syntax == 'html':
        return ENTITY_ONLY.sub(lambda m: html.unescape(m[0]), value)
    return ESCAPE_OR_ENTITY.sub(lambda m: m[1] if m[1] else html.unescape(m[0]), value)


def path_length(raw, syntax='markdown'):
    """Return how many characters of a written destination name the path, before ? or #.

    The ? or # counts after decoding: written as itself, as an escape (\\#), or as an entity (&#35;).
    A percent-encoded one (%23) is part of the file name.
    """
    if syntax == 'wiki':
        position = raw.find('#')
        return len(raw) if position < 0 else position
    pattern = ENTITY_ONLY if syntax == 'html' else ESCAPE_OR_ENTITY
    position = 0
    while position < len(raw):
        match = pattern.match(raw, position)
        if match:
            if decode(match[0], syntax)[:1] in ('#', '?'):
                return position
            position = match.end()
        elif raw[position] in '#?':
            return position
        else:
            position += 1
    return len(raw)


def classify(destination):
    """Name the kind of a decoded destination. Only a relative one depends on the file's folder."""
    if not destination.strip():
        return 'empty'
    if destination[0] in '#?':
        return 'anchor'
    if destination.startswith(('//', '\\\\')) or SCHEME.match(destination):
        return 'absolute'
    if destination[0] == '/':
        return 'root'
    return 'relative'


def label_key(value):
    return ' '.join(value.split()).casefold()


class Cursor:
    """Walk the indentation of one line. A tab moves to the next multiple of four columns."""

    def __init__(self, text, position, end):
        self.text, self.position, self.end, self.column, self.pad = text, position, end, 0, 0

    def indent(self):
        width, column, position = self.pad, self.column + self.pad, self.position
        while position < self.end and self.text[position] in ' \t':
            step = 1 if self.text[position] == ' ' else 4 - column % 4
            width += step
            column += step
            position += 1
        return width, position

    def take(self, count):
        used = min(self.pad, count)
        self.pad -= used
        self.column += used
        count -= used
        while count > 0 and self.position < self.end and self.text[self.position] in ' \t':
            step = 1 if self.text[self.position] == ' ' else 4 - self.column % 4
            self.position += 1
            if step <= count:
                self.column += step
                count -= step
            else:
                self.column += count
                self.pad = step - count
                count = 0

    def skip(self):
        width, position = self.indent()
        self.column += width
        self.position, self.pad = position, 0

    def move(self, count):
        self.position += count
        self.column += count
        self.pad = 0


class Run:
    """The logical text of one paragraph, heading, or HTML block, with each source offset."""

    def __init__(self, source, segments, first_in=None):
        self.text = '\n'.join(source[start:end] for start, end in segments)
        self.offsets = []
        for start, end in segments:
            self.offsets.extend(range(start, end + 1))  # The joining newline maps to the line end.
        self.first_in = first_in

    def span(self, start, end):
        return self.offsets[start], (self.offsets[end - 1] + 1 if end > start else self.offsets[start])


class Scan:
    def __init__(self, text, frontmatter=True, footnotes=True):
        self.text = text
        self.frontmatter = frontmatter
        self.footnotes = footnotes  # False reads "[^n]: text" the plain CommonMark way, as a definition.
        self.links = []
        self.regions = []      # (start, end, reason): text that holds no Markdown link
        self.rejects = {}      # source offset of a refused bracket or attribute -> reason
        self.definitions = {}  # normalized label -> the first definition
        self.open_block = None  # the text that closes a top-level block left open at the end
        self.line_starts = [0] + [match.end() for match in LINE_END.finditer(text)]
        self.runs = []
        self.html_starts = set()
        self.blocks()
        for run, begin in self.runs:
            self.inline(run, begin)
        if footnotes:
            # A vault reads "[^n]: text" as a footnote. Plain CommonMark has no footnotes: it reads
            # "[^n]: file.md" as a definition, and the rest of such a line as paragraph text.
            # Keep both readings. A link that only the plain reading sees is an alternate link:
            # it moves only when it names a real file, and it is never reported as missing.
            taken = {link.dest_start for link in self.links}
            for link in Scan(text, frontmatter, footnotes=False).links:
                if link.dest_start >= 0 and link.kind != 'autolink' and link.dest_start not in taken:
                    link.alternate = True
                    self.links.append(link)
        self.links.sort(key=lambda link: (link.start, link.dest_start))
        self.regions.sort()

    # Lookups

    def line(self, offset):
        low, high = 0, len(self.line_starts)
        while high - low > 1:
            middle = (low + high) // 2
            if self.line_starts[middle] <= offset:
                low = middle
            else:
                high = middle
        return low + 1

    def region(self, offset):
        """Return why the text at this offset holds no Markdown link. The narrowest region wins."""
        inside = [(end - start, reason == 'HTML block text', reason) for start, end, reason in self.regions if start <= offset < end]
        return min(inside)[2] if inside else None

    # Block structure

    def blocks(self):
        text = self.text
        stack = []          # open containers: quote, item, footnote
        self.leaf = None    # the open paragraph, fence, indented code, or HTML block
        frontmatter = self.frontmatter and re.match(r'---[ \t]*(?:\r\n|\n|\r)[\s\S]*?(?:\r\n|\n|\r)---[ \t]*(?:\r\n|\n|\r|$)', text)
        position = 0
        if frontmatter:
            self.regions.append((0, frontmatter.end(), 'frontmatter'))
            position = frontmatter.end()
        size = len(text)
        while position < size:
            match = LINE_END.search(text, position)
            end, following = (match.start(), match.end()) if match else (size, size)
            self.block_line(stack, position, end)
            position = following
        leaf = self.leaf
        if leaf and leaf['t'] == 'fence' and leaf['depth'] == 0:
            self.open_block = leaf['mark'] * leaf['count']
        elif leaf and leaf['t'] == 'html' and leaf['depth'] == 0 and leaf['closer']:
            self.open_block = leaf['closer']
        self.close_leaf(size)

    def close_leaf(self, end):
        leaf, self.leaf = self.leaf, None
        if not leaf:
            return
        if leaf['t'] == 'para':
            self.paragraph(leaf)
        elif leaf['t'] == 'fence':
            self.regions.append((leaf['start'], leaf['end'], 'fenced code block'))
        elif leaf['t'] == 'code':
            self.regions.append((leaf['start'], leaf['end'], 'indented code block'))
        else:
            self.regions.append((leaf['start'], leaf['end'], 'HTML block text'))
            self.html_block(Run(self.text, leaf['segments']))

    def add_text(self, stack, start, end):
        if self.leaf and self.leaf['t'] == 'para':
            self.leaf['segments'].append((start, end))
            return
        self.close_leaf(start)
        first = stack[-1]['t'] if stack and not stack[-1]['child'] else None
        self.leaf = {'t': 'para', 'segments': [(start, end)], 'first_in': first}
        if stack:
            stack[-1]['child'] = True

    def block_line(self, stack, line_start, line_end):
        text = self.text
        cursor = Cursor(text, line_start, line_end)
        matched = 0
        for container in stack:
            width, first = cursor.indent()
            blank = first >= line_end
            if container['t'] == 'quote':
                if width > 3 or blank or text[first] != '>':
                    break
                cursor.skip()
                cursor.move(1)
                if cursor.position < line_end and text[cursor.position] in ' \t':
                    cursor.take(1)
            elif blank:
                if not container['child']:
                    break
            elif width >= container['width']:
                cursor.take(container['width'])
            else:
                break
            matched += 1
        pending = matched < len(stack)
        leaf = self.leaf
        width, first = cursor.indent()
        blank = first >= line_end

        def close_unmatched():
            nonlocal pending
            if pending:
                self.close_leaf(line_start)
                del stack[matched:]
                pending = False

        if not pending and leaf and leaf['t'] == 'fence':
            rest = text[first:line_end]
            closing = re.match(re.escape(leaf['mark']) + '{' + str(leaf['count']) + r',}[ \t]*$', rest)
            leaf['end'] = line_end
            if width <= 3 and closing:
                self.close_leaf(line_end)
            return
        if not pending and leaf and leaf['t'] == 'html':
            if leaf['until'] is None and blank:
                self.close_leaf(line_start)
            else:
                cursor_start = cursor.position
                leaf['segments'].append((cursor_start, line_end))
                leaf['end'] = line_end
                if leaf['until'] is not None and leaf['until'].search(text, cursor_start, line_end):
                    self.close_leaf(line_end)
                return
        if not pending and leaf and leaf['t'] == 'code':
            if blank:
                return
            if width >= 4:
                leaf['end'] = line_end
                return
            self.close_leaf(line_start)
        leaf = self.leaf
        paragraph = bool(leaf and leaf['t'] == 'para')

        while not blank:
            width, first = cursor.indent()
            if width >= 4:
                if paragraph:
                    self.add_text(stack, first, line_end)  # Indented text continues a paragraph.
                    return
                close_unmatched()
                self.close_leaf(line_start)
                if stack:
                    stack[-1]['child'] = True
                self.leaf = {'t': 'code', 'start': line_start, 'end': line_end}
                return
            rest = text[first:line_end]
            if rest[0] == '>':
                close_unmatched()
                self.close_leaf(line_start)
                paragraph = False
                cursor.skip()
                cursor.move(1)
                if cursor.position < line_end and text[cursor.position] in ' \t':
                    cursor.take(1)
                if stack:
                    stack[-1]['child'] = True
                stack.append({'t': 'quote', 'child': False})
                matched = len(stack)
            elif ATX.match(rest):
                close_unmatched()
                self.close_leaf(line_start)
                if stack:
                    stack[-1]['child'] = True
                heading = ATX.match(rest)
                if first + heading.end() < line_end:
                    self.runs.append((Run(text, [(first + heading.end(), line_end)]), 0))
                return
            elif FENCE.match(rest):
                close_unmatched()
                self.close_leaf(line_start)
                if stack:
                    stack[-1]['child'] = True
                fence = FENCE.match(rest)
                marks = fence[1] or fence[3]
                self.leaf = {'t': 'fence', 'mark': marks[0], 'count': len(marks), 'start': line_start, 'end': line_end, 'depth': len(stack)}
                return
            elif self.html_start(rest, paragraph):
                until, closer = self.html_start(rest, paragraph)
                close_unmatched()
                self.close_leaf(line_start)
                if stack:
                    stack[-1]['child'] = True
                self.leaf = {'t': 'html', 'until': until, 'closer': closer, 'start': line_start, 'end': line_end,
                             'segments': [(first, line_end)], 'depth': len(stack)}
                if until is not None and until.search(text, first + 1, line_end):
                    self.close_leaf(line_end)
                return
            elif paragraph and not pending and SETEXT.match(rest):
                self.close_leaf(line_end)  # The paragraph becomes a heading. Its links stay links.
                return
            elif THEMATIC.match(rest):
                close_unmatched()
                self.close_leaf(line_start)
                if stack:
                    stack[-1]['child'] = True
                return
            elif self.footnotes and FOOTNOTE.match(rest):
                close_unmatched()
                self.close_leaf(line_start)
                paragraph = False
                cursor.skip()
                cursor.move(FOOTNOTE.match(rest).end())
                self.rejects[cursor.position - 2] = 'footnote definition'
                if stack:
                    stack[-1]['child'] = True
                stack.append({'t': 'footnote', 'width': 4, 'child': False})
                matched = len(stack)
            else:
                marker = BULLET.match(rest) or ORDERED.match(rest)
                empty = bool(marker) and not rest[marker.end():].strip()
                if marker and paragraph and not pending and (empty or marker.re is ORDERED and marker[1] != '1'):
                    marker = None  # This marker cannot interrupt a paragraph.
                if not marker:
                    break
                close_unmatched()
                self.close_leaf(line_start)
                paragraph = False
                cursor.skip()
                cursor.move(marker.end())
                spaces, after = cursor.indent()
                if after >= line_end or spaces >= 5:
                    spaces = 1
                cursor.take(spaces)
                if stack:
                    stack[-1]['child'] = True
                stack.append({'t': 'item', 'width': width + marker.end() + spaces, 'child': False})
                matched = len(stack)
            width, first = cursor.indent()
            blank = first >= line_end

        if blank:
            close_unmatched()
            if paragraph:
                self.close_leaf(line_start)
            return
        if pending and not paragraph:
            close_unmatched()
        # A paragraph line. With containers still unmatched, this is a lazy continuation.
        self.add_text(stack[:matched] if pending else stack, first, line_end)

    @staticmethod
    def html_start(rest, in_paragraph):
        """Return the end condition of an HTML block that starts here, and the text that closes it."""
        if HTML_LITERAL.match(rest):
            return HTML_LITERAL_END, '</' + re.match(r'<([A-Za-z]+)', rest)[1] + '>'
        if rest.startswith('<!--'):
            return re.compile('-->'), '-->'
        if rest.startswith('<?'):
            return re.compile(r'\?>'), '?>'
        if rest.startswith('<![CDATA['):
            return re.compile(r'\]\]>'), ']]>'
        if re.match(r'<![A-Za-z]', rest):
            return re.compile('>'), '>'
        if HTML_NAMED.match(rest) or not in_paragraph and HTML_COMPLETE.match(rest):
            return None, ''
        return None

    def html_block(self, run):
        position = 0
        while True:
            match = HTML_BLOCK_PART.search(run.text, position)
            if not match:
                break
            position = match.end()
            if match[1]:
                self.regions.append((*run.span(match.start(), match.end()), 'HTML comment'))
                continue
            self.attributes(run, match.start(), match.end())
            name = re.match(r'<(script|style|textarea)\b', match[0], re.I)
            if name:
                # The text of these elements is not HTML. A tag written inside is only text.
                close = re.compile('</' + name[1] + r'\s*>', re.I).search(run.text, position)
                end = close.start() if close else len(run.text)
                if end > position:
                    self.regions.append((*run.span(position, end), 'HTML raw text'))
                position = end
        self.loose_attributes(run, 0)

    def attributes(self, run, start, end):
        """Read each href and src of one tag. A name such as data-src is refused, with the reason."""
        for match in ATTRIBUTE_LINK.finditer(run.text, start, end):
            if re.match(r'[A-Za-z0-9_.:-]', run.text[match.start() - 1]):
                self.rejects.setdefault(run.offsets[match.start()], 'part of another attribute name')
                continue
            group = 1 if match[1] is not None else 2 if match[2] is not None else 3
            first, last = run.span(match.start(group), match.end(group))
            self.links.append(Link('html', *run.span(match.start(), match.end()), self.line(first), first, last, self.text[first:last]))
            self.html_starts.add(run.offsets[match.start()])

    def loose_attributes(self, run, begin):
        """Refuse each href or src that stands outside a tag. The check sees every such word."""
        for match in ATTRIBUTE_LINK.finditer(run.text, begin):
            offset = run.offsets[match.start()]
            if offset not in self.html_starts:
                self.rejects.setdefault(offset, 'attribute text outside an HTML tag')

    # Paragraphs: definitions first, then inline links

    def paragraph(self, leaf):
        run = Run(self.text, leaf['segments'], leaf['first_in'])
        text, position = run.text, 0
        while True:
            parsed = self.definition(run, position)
            if parsed is None:
                break
            position = parsed
        if position < len(text):
            self.runs.append((run, position))

    def definition(self, run, start):
        text, size = run.text, len(run.text)
        if start >= size or text[start] != '[':
            return None
        close = self.label_end(text, start)
        if close is None or close + 1 >= size or text[close + 1] != ':':
            return None
        label = text[start + 1:close]
        colon = run.offsets[close]
        if not label.strip() or label.startswith('^') and self.footnotes:
            self.rejects[colon] = 'a footnote or an empty label, not a definition'
            return None
        begin = self.space(text, close + 2)
        destination = self.destination(text, begin)
        if not destination or destination[1] == destination[0] and not destination[2]:
            self.rejects[colon] = 'no destination after the label'
            return None
        dest_start, dest_end, angle = destination
        after = dest_end + (1 if angle else 0)
        end = None
        title_start = self.space(text, after)
        if title_start > after and title_start < size and text[title_start] in '"\'(':
            title_end = self.title(text, title_start)
            if title_end is not None:
                end = self.line_rest(text, title_end)
        if end is None:
            end = self.line_rest(text, after)
        if end is None:
            self.rejects[colon] = 'text follows the destination on its line'
            return None
        first, last = run.span(dest_start, dest_end)
        key = label_key(label)
        link = Link('definition', run.offsets[start], run.span(start, len(text[:end].rstrip('\n')))[1], self.line(first), first, last,
                    self.text[first:last], label, key)
        self.links.append(link)
        self.definitions.setdefault(key, link)
        return end

    @staticmethod
    def label_end(text, start):
        position = start + 1
        while position < len(text) and position - start <= 1000:
            char = text[position]
            if char == '\\' and position + 1 < len(text) and text[position + 1] in PUNCTUATION:
                position += 2
            elif char == '[':
                return None
            elif char == ']':
                return position
            else:
                position += 1
        return None

    @staticmethod
    def space(text, position):
        """Skip spaces and tabs, with at most one line end."""
        size = len(text)
        while position < size and text[position] in ' \t':
            position += 1
        if position < size and text[position] == '\n':
            position += 1
            while position < size and text[position] in ' \t':
                position += 1
        return position

    @staticmethod
    def line_rest(text, position):
        """Return the start of the next line when only spaces remain on this one."""
        size = len(text)
        while position < size and text[position] in ' \t':
            position += 1
        if position >= size:
            return size
        return position + 1 if text[position] == '\n' else None

    @staticmethod
    def destination(text, position):
        """Return (start, end, angle) of the destination text, or None."""
        size = len(text)
        if position < size and text[position] == '<':
            cursor = position + 1
            while cursor < size:
                char = text[cursor]
                if char == '\\' and cursor + 1 < size and text[cursor + 1] in PUNCTUATION:
                    cursor += 2
                elif char == '>':
                    return position + 1, cursor, True
                elif char in '<\n':
                    return None
                else:
                    cursor += 1
            return None
        cursor, depth = position, 0
        while cursor < size:
            char = text[cursor]
            if char == '\\' and cursor + 1 < size and text[cursor + 1] in PUNCTUATION:
                cursor += 2
                continue
            if char in ' \t\n' or ord(char) < 32 or ord(char) == 127:
                break
            if char == '(':
                depth += 1
            elif char == ')':
                if not depth:
                    break
                depth -= 1
            cursor += 1
        return None if depth else (position, cursor, False)

    @staticmethod
    def title(text, position):
        opening = text[position]
        closing = ')' if opening == '(' else opening
        cursor, size = position + 1, len(text)
        while cursor < size:
            char = text[cursor]
            if char == '\\' and cursor + 1 < size and text[cursor + 1] in PUNCTUATION:
                cursor += 2
            elif char == closing:
                return cursor + 1
            elif char == '(' and opening == '(':
                return None
            else:
                cursor += 1
        return None

    def inline(self, run, begin):
        text, size = run.text, len(run.text)
        position = begin
        if run.first_in == 'item':
            box = TASK.match(text, position)
            if box:
                self.rejects[run.offsets[box.end() - 1]] = 'task list checkbox'
                position = box.end()
        elif run.first_in == 'quote':
            callout = CALLOUT.match(text, position)
            if callout:
                self.rejects[run.offsets[text.index(']', position)]] = 'callout marker'
                position = callout.end()
        openers = []

        def refuse(index, reason):
            # Record a refusal only where a destination could follow: "](" or "]:".
            if index + 1 < size and text[index + 1] in '(:':
                self.rejects.setdefault(run.offsets[index], reason)

        while position < size:
            char = text[position]
            if char == '\\' and position + 1 < size and text[position + 1] in PUNCTUATION:
                if text.startswith('[[', position + 1):
                    self.rejects.setdefault(run.offsets[position + 1], 'escaped bracket')
                position += 2
            elif char == '`':
                stop = position
                while stop < size and text[stop] == '`':
                    stop += 1
                close = self.code_close(text, stop, stop - position)
                if close is not None:
                    self.regions.append((*run.span(position, close), 'code span'))
                position = close if close is not None else stop
            elif char == '<':
                auto = AUTOLINK.match(text, position)
                tag = None if auto else HTML_INLINE.match(text, position)
                if auto:
                    first, last = run.span(auto.start(1), auto.end(1))
                    self.links.append(Link('autolink', *run.span(auto.start(), auto.end()), self.line(first), first, last, self.text[first:last]))
                    position = auto.end()
                elif tag:
                    if tag[2]:
                        self.attributes(run, tag.start(), tag.end())
                    self.regions.append((*run.span(tag.start(), tag.end()), 'HTML comment' if tag[1] else 'HTML tag'))
                    position = tag.end()
                else:
                    position += 1
            elif char == '[' or char == '!' and text.startswith('[', position + 1):
                bracket = position + (char == '!')
                wiki = WIKILINK.match(text, bracket) if text.startswith('[[', bracket) else None
                if wiki and wiki[1].strip():
                    self.wikilink(run, position, bracket, wiki)
                    position = wiki.end()
                    refuse(position - 1, 'text after a wikilink')
                    for opener in openers:
                        opener['active'] = opener['active'] and opener['image']
                    continue
                if text.startswith('[[', bracket):
                    self.rejects.setdefault(run.offsets[bracket], 'empty wikilink' if wiki else 'no closing brackets on the line')
                openers.append({'bracket': bracket, 'start': position, 'image': char == '!', 'active': True})
                position = bracket + 1
            elif char == ']':
                if not openers:
                    refuse(position, 'no opening bracket')
                    position += 1
                    continue
                opener = openers.pop()
                if not opener['active']:
                    refuse(position, 'the link text holds another link')
                    position += 1
                    continue
                label = text[opener['bracket'] + 1:position]
                if self.footnotes and not opener['image'] and re.fullmatch(r'\^[^\s\]]+', label):
                    refuse(position, 'footnote reference')
                    position += 1
                    continue
                link = self.inline_link(run, opener, position) if text.startswith('(', position + 1) else None
                end = None
                if link:
                    end = link[1]
                    link = link[0]
                else:
                    refuse(position, 'no valid destination and closing parenthesis' if text.startswith('(', position + 1)
                           else 'a definition must start a paragraph')
                    key, end, defined = self.reference(text, label, position)
                    if key is not None:
                        start = run.offsets[opener['start']]
                        link = Link('reference', start, run.span(opener['start'], end)[1], self.line(start), label=label, key=key, defined=defined)
                        refuse(end - 1, 'text after a reference link')
                if link is None:
                    position += 1
                    continue
                self.links.append(link)
                if not link.defined:
                    position += 1  # No definition: plain text. Its second bracket pair can still be a link.
                    continue
                if not opener['image']:
                    for other in openers:
                        other['active'] = other['active'] and other['image']
                position = end
            else:
                position += 1
        self.loose_attributes(run, begin)

    @staticmethod
    def code_close(text, position, count):
        size = len(text)
        while position < size:
            if text[position] != '`':
                position += 1
                continue
            stop = position
            while stop < size and text[stop] == '`':
                stop += 1
            if stop - position == count:
                return stop
            position = stop
        return None

    def inline_link(self, run, opener, close):
        text, size = run.text, len(run.text)
        begin = self.space(text, close + 2)
        destination = self.destination(text, begin)
        if not destination:
            return None
        dest_start, dest_end, angle = destination
        after = dest_end + (1 if angle else 0)
        position = self.space(text, after)
        if position > after and position < size and text[position] in '"\'(':
            title_end = self.title(text, position)
            if title_end is not None:
                position = self.space(text, title_end)
        if position >= size or text[position] != ')':
            return None
        first, last = run.span(dest_start, dest_end)
        start = run.offsets[opener['start']]
        link = Link('image' if opener['image'] else 'inline', start, run.span(opener['start'], position + 1)[1], self.line(first),
                    first, last, self.text[first:last], text[opener['bracket'] + 1:close])
        return link, position + 1

    def reference(self, text, label, close):
        """Return (key, end, defined) for a reference link whose text ends at close, or (None, None, None)."""
        if text.startswith('[', close + 1):
            second = self.label_end(text, close + 1)
            if second is not None:
                written = text[close + 2:second]
                key = label_key(written) if written.strip() else label_key(label)
                if key in self.definitions:
                    return key, second + 1, True
                if written.strip():
                    return key, second + 1, False
                return None, None, None
        key = label_key(label)
        if key and '[' not in label.replace('\\[', '') and key in self.definitions:
            return key, close + 1, True
        return None, None, None

    def wikilink(self, run, start, bracket, match):
        content = match[1]
        bar = re.search(r'\\?\|', content)
        target = content[:bar.start()] if bar else content
        alias = content[bar.end():] if bar else ''
        first = run.offsets[match.start(1)]
        self.links.append(Link('embed' if start != bracket else 'wikilink', run.offsets[start], run.span(start, match.end())[1],
                               self.line(first), first, first + len(target), target, alias or target))


def scan(text, frontmatter=True):
    return Scan(text, frontmatter)


def with_prefix(prefix, raw):
    """Put a folder prefix before a written path. Keep the author's spelling of the rest.

    Only a leading ./ or ../ of the written path is folded into the prefix.
    """
    parts = [part for part in prefix.split('/') if part and part != '.']
    while True:
        if raw == '.' or raw.startswith('./'):
            raw = raw[2:]
        elif raw == '..' or raw.startswith('../'):
            if parts and parts[-1] != '..':
                parts.pop()
            else:
                parts.append('..')
            raw = raw[3:]
        else:
            break
    return '/'.join(parts + [raw]) if raw or not parts else '/'.join(parts)


def rewrite(text, relocate):
    """Move each relative destination to its new folder. Change nothing else.

    relocate(path, mode) answers for one decoded path. The mode is vault, plain, or wiki.
    vault: a Markdown link; the path can also start at the vault root, or leave out the .md of a note.
    plain: an HTML attribute or an alternate link; only a plain relative path counts.
    For both it returns ((prefix, suffix), None): the folder prefix to put before the written path,
    and a suffix to add, such as a left-out .md. The written path itself stays.
    wiki: a wikilink; it returns (new relative path, None). For a target it cannot find: (None, reason).

    Returns the new text and one outcome for each destination:
    rewritten, untouched (with the reason), or unresolved (with the reason).
    """
    found = Scan(text, frontmatter=False)
    edits, outcomes = [], []
    for link in sorted(found.links, key=lambda link: link.alternate):  # The vault's own reading goes first.
        if link.kind == 'reference':
            continue
        outcome = {'kind': link.kind, 'line': link.line, 'destination': link.raw}
        length = path_length(link.raw, link.syntax)
        path = decode(link.raw[:length], link.syntax)
        if link.syntax == 'wiki':
            kind = 'relative' if path.strip() else 'anchor'
        else:
            kind = 'absolute' if link.kind == 'autolink' else classify(decode(link.raw, link.syntax))
        if kind != 'relative':
            if not link.alternate:
                outcomes.append({**outcome, 'status': 'untouched', 'reason': kind})
            continue
        mode = 'wiki' if link.syntax == 'wiki' else 'plain' if link.syntax == 'html' or link.alternate else 'vault'
        target, reason = relocate(path.strip() if mode == 'wiki' else path, mode)
        if target is None:
            # An alternate link that names no file is only footnote text.
            if not link.alternate:
                outcomes.append({**outcome, 'status': 'unresolved', 'reason': reason})
            continue
        if link.syntax == 'wiki':
            target = quote(target, safe='/.-_~')
            label = re.sub(r'([\\\[\]])', r'\\\1', link.label.strip())
            fragment = quote(link.raw[length:], safe="#^-._~!$&'*+,;=:@/?")
            edit = (link.start, link.end, ('!' if link.kind == 'embed' else '') + '[' + label + '](' + target + fragment + ')')
        else:
            prefix, suffix = target
            target = with_prefix(quote(prefix, safe='/.-_~'), link.raw[:length]) + suffix
            edit = (link.dest_start, link.dest_start + length, target)
        if any(start < edit[1] and edit[0] < end for start, end, _ in edits):
            continue  # Two readings of the same text: the first one stands.
        edits.append(edit)
        outcomes.append({**outcome, 'status': 'rewritten', 'to': target})
    outcomes.sort(key=lambda outcome: outcome['line'])
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    return text, outcomes


def check_links(pages):
    """Return one error line for each link that fails the independent link check."""
    from link_check import check_page
    return [f'{page}: {line}' for page in pages for line in check_page(page)['failures']]
