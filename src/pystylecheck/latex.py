"""Parse a LaTeX source into a :class:`Document`.

A document offers several views of the same source:

* ``blocks``: prose blocks (paragraphs, headings, captions, footnotes, list
  items, table cells) where markup is removed.  Every prose character maps
  back to an exact source offset, so a finding in prose can be reported at
  the right line and column even when the phrase spans lines or markup
  (``\\emph{the} the``).
* ``events``: the document structure in order (headings, paragraphs,
  lists, floats, code blocks...).
* ``source_view``: the source with comments removed and the contents of
  math, verbatim and "ignored" command arguments masked, as style-check.rb
  does before applying its regular expressions.
* collected facts: labels, references, citations, floats, tables, math.
"""

from __future__ import annotations

import bisect
import os
import re
from dataclasses import dataclass, field

from pylatexenc import latexwalker as lw
from pylatexenc.latex2text import LatexNodes2Text
from pylatexenc.macrospec import (
    EnvironmentSpec,
    MacroSpec,
    MacroStandardArgsParser,
    ParsedMacroArgs,
)

from . import latexdb as db
from .latexdb import (
    PH_CITE,
    PH_CODE,
    PH_DISPLAY,
    PH_MATH,
    PH_OTHER,
    PH_REF,
    PH_SEP,
    PH_UNIT,
    Definitions,
)

MASK = "\x07"
BLOCK_SEP = "\u2029"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Block:
    """A run of prose with a source offset for every character."""

    kind: str  # paragraph, heading, title, caption, footnote, item, cell, float-text
    text: str
    starts: list[int]
    ends: list[int]
    pos: int = 0  # source position of the construct
    end: int = 0
    start_reason: str = ""
    end_reason: str = ""
    level: int | None = None
    macro: str | None = None
    env: str | None = None

    def span(self, i: int, j: int) -> tuple[int, int]:
        """Source span of prose characters [i, j)."""
        if not self.starts:
            return (self.pos, self.pos)
        if j <= i:
            k = min(i, len(self.starts) - 1)
            return (self.starts[k], self.starts[k])
        return (self.starts[i], self.ends[j - 1])

    def is_verbatim(self, src: str, i: int, j: int) -> bool:
        """True if prose [i, j) is a contiguous, unmodified copy of the source."""
        if j <= i:
            return True
        s, e = self.starts[i], self.ends[j - 1]
        return e - s == j - i and src[s:e] == self.text[i:j]

    @property
    def has_words(self) -> bool:
        return bool(re.search(r"[^\W\d_]", self.text))


@dataclass
class Heading:
    level: int
    macro: str
    starred: bool
    block: Block
    pos: int
    end: int


@dataclass
class MathInfo:
    pos: int
    end: int
    body_start: int
    body_end: int
    display: bool
    env: str | None = None


@dataclass
class TabularInfo:
    env: str
    pos: int
    end: int
    colspec: str | None
    colspec_pos: int | None
    hlines: list[tuple[int, int]] = field(default_factory=list)
    in_float: bool = False


@dataclass
class FloatInfo:
    env: str
    pos: int
    end: int
    placement: str | None = None
    placement_pos: int | None = None
    labels: list[tuple[str, int, int]] = field(default_factory=list)
    captions: list[Block] = field(default_factory=list)
    caption_positions: list[int] = field(default_factory=list)
    content_positions: list[int] = field(default_factory=list)
    graphics: list[tuple[str, int, int]] = field(default_factory=list)
    tabulars: list[TabularInfo] = field(default_factory=list)
    has_frame: bool = False


@dataclass
class Ref:
    macro: str
    keys: list[str]
    pos: int
    end: int


@dataclass
class Label:
    key: str
    pos: int
    end: int
    env: str | None
    float_index: int | None


@dataclass
class Include:
    macro: str
    target: str
    pos: int
    end: int


@dataclass
class MacroUse:
    macro: str
    pos: int
    end: int
    envs: tuple[str, ...]


@dataclass
class Event:
    kind: str  # heading, paragraph, list, code, float, tabular, include, eof
    pos: int
    obj: object = None


@dataclass
class View:
    """A transformed copy of the source with a map back to source offsets."""

    text: str
    offsets: list[int]

    def src(self, i: int) -> int:
        if i < len(self.offsets):
            return self.offsets[i]
        return self.offsets[-1] + 1 if self.offsets else 0

    def src_span(self, i: int, j: int) -> tuple[int, int]:
        if j <= i:
            p = self.src(i)
            return (p, p)
        return (self.offsets[i], self.offsets[j - 1] + 1)


@dataclass
class Suppressions:
    """Inline ``% pystylecheck:`` directives."""

    # line -> set of ids (None: everything)
    lines: dict[int, set[str] | None] = field(default_factory=dict)
    # (first line, last line, ids or None)
    regions: list[tuple[int, int, set[str] | None]] = field(default_factory=list)

    def suppressed(self, line: int, ids: set[str]) -> bool:
        if line in self.lines:
            s = self.lines[line]
            if s is None or s & ids:
                return True
        for a, b, s in self.regions:
            if a <= line <= b and (s is None or s & ids):
                return True
        return False


class Document:
    """A parsed LaTeX file."""

    def __init__(self, path: str, source: str):
        self.path = path
        self.source = source
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", source)]
        self.blocks: list[Block] = []
        self.events: list[Event] = []
        self.headings: list[Heading] = []
        self.maths: list[MathInfo] = []
        self.floats: list[FloatInfo] = []
        self.tabulars: list[TabularInfo] = []
        self.refs: list[Ref] = []
        self.cites: list[Ref] = []
        self.labels: list[Label] = []
        self.includes: list[Include] = []
        self.bold: list[MacroUse] = []
        self.color: list[MacroUse] = []
        self.graphics: list[tuple[str, int, int]] = []
        self.code_spans: list[tuple[int, int]] = []  # verbatim, \verb, \url...
        self.comment_spans: list[tuple[int, int]] = []
        self.removed_spans: list[tuple[int, int]] = []  # comment env, \iffalse
        self.masked_spans: list[tuple[int, int]] = []
        self.parse_errors: list[tuple[int, str]] = []
        self.is_root = "\\begin{document}" in source
        self.frenchspacing = bool(re.search(r"\\frenchspacing\b", source))
        self.declared_language = db.declared_language(source)
        self.language: str = "en"
        self.suppressions = Suppressions()
        self.source_view: View = View("", [])
        self.prose: View = View("", [])
        self._prose_block_starts: list[int] = []

    # -- positions -------------------------------------------------------
    def line_col(self, offset: int) -> tuple[int, int]:
        """1-based line and column of a source offset."""
        offset = max(0, min(offset, len(self.source)))
        line = bisect.bisect_right(self.line_starts, offset) - 1
        return line + 1, offset - self.line_starts[line] + 1

    def line_text(self, line: int) -> str:
        if line < 1 or line > len(self.line_starts):
            return ""
        s = self.line_starts[line - 1]
        e = self.source.find("\n", s)
        return self.source[s : e if e >= 0 else len(self.source)]

    def in_spans(self, offset: int, spans: list[tuple[int, int]]) -> bool:
        return any(a <= offset < b for a, b in spans)

    def in_code(self, offset: int) -> bool:
        return self.in_spans(offset, self.code_spans)

    def in_comment(self, offset: int) -> bool:
        return self.in_spans(offset, self.comment_spans) or self.in_spans(offset, self.removed_spans)

    def in_math(self, offset: int) -> bool:
        return any(m.body_start <= offset < m.body_end for m in self.maths)

    def is_hidden(self, offset: int) -> bool:
        """True for offsets in comments, code, removed regions or math."""
        return self.in_comment(offset) or self.in_code(offset) or self.in_math(offset)

    def block_of_prose(self, i: int) -> int:
        """Index of the block containing prose-view character i."""
        return bisect.bisect_right(self._prose_block_starts, i) - 1

    def prose_blocks(self, *kinds: str) -> list[Block]:
        if not kinds:
            return self.blocks
        return [b for b in self.blocks if b.kind in kinds]


# ---------------------------------------------------------------------------
# Custom argument parsers for verbatim-like constructs
# ---------------------------------------------------------------------------


def _chars(w, ps, s: str, pos: int, n: int):
    return w.make_node(lw.LatexCharsNode, parsing_state=ps, chars=s, pos=pos, len=n)


class _VerbatimEnvParser(MacroStandardArgsParser):
    """Arguments of a verbatim environment: optional standard args, then the
    raw body up to ``\\end{name}``."""

    def __init__(self, envname: str, preargs: str = ""):
        super().__init__(argspec=preargs)
        self.envname = envname

    def parse_args(self, w, pos, parsing_state=None):
        if parsing_state is None:
            parsing_state = w.make_parsing_state()
        if self.argspec:
            argd, p0, n0 = super().parse_args(w, pos, parsing_state=parsing_state)
            args = list(argd.argnlist)
            p = p0 + n0
        else:
            args, p = [], pos
        endtag = "\\end{%s}" % self.envname
        e = w.s.find(endtag, p)
        if e < 0:
            e = len(w.s)
        args.append(_chars(w, parsing_state, w.s[p:e], p, e - p))
        return (ParsedMacroArgs(argspec=self.argspec + "{", argnlist=args), pos, e - pos)


def _find_matching_brace(s: str, start: int) -> int:
    """Index just after the brace closing the group opened at s[start]."""
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(s)


class _VerbArgParser(MacroStandardArgsParser):
    """``\\url{...}``, ``\\lstinline|...|``, ``\\href{url}{text}``...

    ``pre`` standard args are parsed first, then one verbatim argument
    (delimited by braces or by any character), then ``post`` standard args.
    """

    def __init__(self, pre: str = "", post: str = "", braces_only: bool = False):
        super().__init__(argspec=pre + "{" + post)
        self.pre = pre
        self.post = post
        self.braces_only = braces_only

    def parse_args(self, w, pos, parsing_state=None):
        if parsing_state is None:
            parsing_state = w.make_parsing_state()
        args = []
        p = pos
        if self.pre:
            argd, p0, n0 = MacroStandardArgsParser(self.pre).parse_args(w, p, parsing_state=parsing_state)
            args.extend(argd.argnlist)
            p = p0 + n0
        s = w.s
        q = p
        while q < len(s) and s[q] in " \t\n":
            q += 1
        if q >= len(s):
            args.append(None)
            return (ParsedMacroArgs(argspec=self.argspec, argnlist=args + [None] * len(self.post)), pos, q - pos)
        if s[q] == "{":
            e = _find_matching_brace(s, q)
            body = (q + 1, max(q + 1, e - 1))
        elif self.braces_only:
            args.append(None)
            args.extend([None] * len(self.post))
            return (ParsedMacroArgs(argspec=self.argspec, argnlist=args), pos, p - pos)
        else:
            d = s[q]
            e = s.find(d, q + 1)
            nl = s.find("\n", q + 1)
            if e < 0 or (0 <= nl < e):
                e = q  # malformed; give up on this argument
                body = (q, q)
            else:
                body = (q + 1, e)
                e += 1
        node = _chars(w, parsing_state, s[body[0] : body[1]], body[0], body[1] - body[0])
        args.append(node)
        p = e
        if self.post:
            argd, p0, n0 = MacroStandardArgsParser(self.post).parse_args(w, p, parsing_state=parsing_state)
            args.extend(argd.argnlist)
            p = p0 + n0
        return (ParsedMacroArgs(argspec=self.argspec, argnlist=args), pos, p - pos)


def make_context(defs: Definitions):
    """Build a pylatexenc context database that knows our macros."""
    ctx = lw.get_default_latex_context_db()
    macros = []
    for name, spec in db.MACRO_ARGSPECS.items():
        macros.append(MacroSpec(name, spec))
    for name, spec in defs.macro_argspecs.items():
        if name not in db.MACRO_ARGSPECS:
            macros.append(MacroSpec(name, spec))
    for name in defs.ignored_macros:
        if name not in db.MACRO_ARGSPECS and name not in defs.macro_argspecs:
            macros.append(MacroSpec(name, "*[{"))
    macros += [
        MacroSpec("url", args_parser=_VerbArgParser(braces_only=True)),
        MacroSpec("nolinkurl", args_parser=_VerbArgParser(braces_only=True)),
        MacroSpec("path", args_parser=_VerbArgParser()),
        MacroSpec("href", args_parser=_VerbArgParser(pre="[", post="{", braces_only=True)),
        MacroSpec("lstinline", args_parser=_VerbArgParser(pre="[")),
        MacroSpec("mintinline", args_parser=_VerbArgParser(pre="[{")),
        MacroSpec("Verb", args_parser=_VerbArgParser(pre="*[")),
    ]
    envs = []
    for name, spec in db.ENV_ARGSPECS.items():
        envs.append(EnvironmentSpec(name, spec))
    for name in sorted(db.VERBATIM_ENVS | defs.verbatim_envs):
        envs.append(
            EnvironmentSpec(name, args_parser=_VerbatimEnvParser(name, db.VERBATIM_ENV_PREARGS.get(name, "[" if name in defs.verbatim_envs else "")))
        )
    ctx.add_context_category("pystylecheck", macros=macros, environments=envs, prepend=True)
    return ctx


# ---------------------------------------------------------------------------
# The walker
# ---------------------------------------------------------------------------

_BLANK_LINE = re.compile(r"\n[ \t]*\n\s*")
_DIRECTIVE = re.compile(
    r"pystylecheck\s*:\s*(ignore-next-line|ignore|disable|enable|off|on)(?:\s*[=:]\s*([\w@:,\s-]+))?",
    re.I,
)

_l2t = LatexNodes2Text(math_mode="verbatim", keep_comments=False, strict_latex_spaces=False)


class _Builder:
    def __init__(self, kind: str, pos: int, start_reason: str = "", **meta):
        self.kind = kind
        self.pos = pos
        self.start_reason = start_reason
        self.meta = meta
        self.chars: list[str] = []
        self.starts: list[int] = []
        self.ends: list[int] = []

    def add_source(self, text: str, pos: int) -> None:
        for k, c in enumerate(text):
            self.chars.append(c)
            self.starts.append(pos + k)
            self.ends.append(pos + k + 1)

    def add_rendered(self, text: str, start: int, end: int) -> None:
        for c in text:
            self.chars.append(c)
            self.starts.append(start)
            self.ends.append(end)

    def empty(self) -> bool:
        return not "".join(self.chars).strip()

    def build(self, end: int, end_reason: str) -> Block:
        return Block(
            kind=self.kind,
            text="".join(self.chars),
            starts=self.starts,
            ends=self.ends,
            pos=self.pos,
            end=end,
            start_reason=self.start_reason,
            end_reason=end_reason,
            **self.meta,
        )


def _nodes(n) -> list:
    return [x for x in (getattr(n, "nodelist", None) or []) if x is not None]


def _args(n) -> list:
    d = getattr(n, "nodeargd", None)
    if d is None or not getattr(d, "argnlist", None):
        return []
    return list(d.argnlist)


def _argspec(n) -> str:
    d = getattr(n, "nodeargd", None)
    return getattr(d, "argspec", "") or "" if d is not None else ""


def _mandatory_args(n) -> list:
    spec = _argspec(n)
    return [a for a, s in zip(_args(n), spec) if s == "{" and a is not None]


def _last_mandatory(n):
    m = _mandatory_args(n)
    return m[-1] if m else None


def _optional_args(n) -> list:
    spec = _argspec(n)
    return [a for a, s in zip(_args(n), spec) if s == "[" and a is not None]


def _is_star(n) -> bool:
    spec = _argspec(n)
    return any(s == "*" and a is not None for a, s in zip(_args(n), spec))


def _arg_text(src: str, a) -> str:
    """Raw source text inside an argument node (without braces)."""
    if a is None:
        return ""
    if isinstance(a, lw.LatexGroupNode):
        inner = _nodes(a)
        if not inner:
            return ""
        s = inner[0].pos
        e = inner[-1].pos + inner[-1].len
        return src[s:e]
    return src[a.pos : a.pos + a.len]


def _arg_inner_span(a) -> tuple[int, int] | None:
    if a is None:
        return None
    if isinstance(a, lw.LatexGroupNode):
        d = a.delimiters
        if d and len(d) == 2 and d[0] and d[1]:
            return (a.pos + len(d[0]), a.pos + a.len - len(d[1]))
        return (a.pos, a.pos + a.len)
    return (a.pos, a.pos + a.len)


class _Walker:
    def __init__(self, doc: Document, defs: Definitions):
        self.doc = doc
        self.src = doc.source
        self.defs = defs
        self.env_stack: list[str] = []
        self.float_stack: list[FloatInfo] = []
        self.tabular_stack: list[TabularInfo] = []
        self.list_depth = 0
        self.para: _Builder = _Builder("paragraph", 0, "start")
        self.target: _Builder = self.para
        self.after_comment_newline = False
        self.in_preamble = doc.is_root
        self.verbatim_envs = db.VERBATIM_ENVS | defs.verbatim_envs
        self.skip_envs = db.SKIP_ENVS | defs.ignored_envs

    # -- block management --------------------------------------------------
    def close_para(self, pos: int, reason: str, next_kind: str = "paragraph", next_reason: str = "") -> None:
        """Finish the current flow block and start a new one."""
        b = self.para
        if not b.empty() and not self.in_preamble:
            block = b.build(pos, reason)
            if block.kind == "paragraph" and PH_SEP in block.text:
                block.kind = "cell"  # rows of a table body pulled in with \input
            self.doc.blocks.append(block)
            self.doc.events.append(Event("paragraph", b.pos, block))
        self.para = _Builder(next_kind, pos, next_reason or reason, env=self.env_stack[-1] if self.env_stack else None)
        if self.target is b:
            self.target = self.para

    def sub_block(self, kind: str, pos: int, **meta) -> _Builder:
        return _Builder(kind, pos, "", env=self.env_stack[-1] if self.env_stack else None, **meta)

    def finish_sub(self, b: _Builder, end: int) -> Block:
        block = b.build(end, "end")
        self.doc.blocks.append(block)
        return block

    def mask(self, a: int, b: int) -> None:
        if b > a:
            self.doc.masked_spans.append((a, b))

    def mask_args(self, n) -> None:
        for a in _args(n):
            sp = _arg_inner_span(a)
            if sp:
                self.mask(*sp)

    def flow_kind(self) -> str:
        if self.float_stack:
            return "float-text"
        if self.tabular_stack:
            return "cell"
        if self.list_depth:
            return "item"
        return "paragraph"

    # -- traversal ---------------------------------------------------------
    def visit_list(self, nodes: list) -> None:
        i = 0
        nodes = [n for n in nodes if n is not None]
        while i < len(nodes):
            n = nodes[i]
            if isinstance(n, lw.LatexMacroNode) and n.macroname == "iffalse":
                j, depth = i + 1, 1
                while j < len(nodes):
                    m = nodes[j]
                    if isinstance(m, lw.LatexMacroNode):
                        if m.macroname.startswith("if"):
                            depth += 1
                        elif m.macroname == "fi":
                            depth -= 1
                            if depth == 0:
                                break
                    j += 1
                end = nodes[j].pos + nodes[j].len if j < len(nodes) else len(self.src)
                self.doc.removed_spans.append((n.pos, end))
                i = j + 1
                continue
            self.visit(n)
            i += 1

    def visit(self, n) -> None:
        if isinstance(n, lw.LatexCharsNode):
            self.visit_chars(n)
            return
        was_after_comment = self.after_comment_newline
        self.after_comment_newline = False
        if isinstance(n, lw.LatexCommentNode):
            self.visit_comment(n)
        elif isinstance(n, lw.LatexGroupNode):
            self.visit_list(_nodes(n))
        elif isinstance(n, lw.LatexMacroNode):
            self.visit_macro(n)
        elif isinstance(n, lw.LatexEnvironmentNode):
            self.visit_env(n)
        elif isinstance(n, lw.LatexMathNode):
            self.visit_math(n)
        elif isinstance(n, lw.LatexSpecialsNode):
            self.visit_specials(n)
        del was_after_comment

    def visit_chars(self, n) -> None:
        text = n.chars
        pos = n.pos
        if self.after_comment_newline and re.match(r"[ \t]*\n", text):
            # "% comment\n\n": the empty line after the comment ends the paragraph
            m = re.match(r"[ \t]*\n\s*", text)
            self.paragraph_break(pos + m.start())
            text, pos = text[m.end() :], pos + m.end()
        self.after_comment_newline = False
        last = 0
        for m in _BLANK_LINE.finditer(text):
            self.target.add_source(text[last : m.start()], pos + last)
            self.paragraph_break(pos + m.start())
            last = m.end()
        self.target.add_source(text[last:], pos + last)

    def paragraph_break(self, pos: int) -> None:
        if self.target is self.para:
            self.close_para(pos, "blank", self.flow_kind(), "blank")
        else:
            # paragraph break inside a footnote or caption: keep going
            self.target.add_rendered("\n\n", pos, pos)

    def visit_comment(self, n) -> None:
        s = n.pos
        e = self.src.find("\n", s)
        if e < 0:
            e = len(self.src)
        self.doc.comment_spans.append((s, e))
        self.parse_directive(n.comment, s)
        self.after_comment_newline = e < len(self.src) and n.pos + n.len > e

    def parse_directive(self, comment: str, pos: int) -> None:
        m = _DIRECTIVE.search(comment)
        if not m:
            return
        action = m.group(1).lower()
        ids = None
        if m.group(2):
            ids = {x.strip() for x in re.split(r"[,\s]+", m.group(2)) if x.strip()} or None
        line, _ = self.doc.line_col(pos)
        sup = self.doc.suppressions
        if action == "ignore":
            sup.lines[line] = None if ids is None or sup.lines.get(line, set()) is None else (sup.lines.get(line) or set()) | ids
        elif action == "ignore-next-line":
            sup.lines[line + 1] = None if ids is None else (sup.lines.get(line + 1) or set()) | ids
        elif action in ("disable", "off"):
            sup.regions.append((line, 10**9, ids))
        elif action in ("enable", "on"):
            # close the most recent matching open region
            for k in range(len(sup.regions) - 1, -1, -1):
                a, b, s = sup.regions[k]
                if b == 10**9 and (ids is None or s is None or s == ids):
                    sup.regions[k] = (a, line, s)
                    break

    def visit_specials(self, n) -> None:
        sc = n.specials_chars
        end = n.pos + n.len
        if sc == "~":
            self.target.add_rendered("\u00a0", n.pos, end)
        elif sc == "&":
            self.target.add_rendered(PH_SEP, n.pos, end)
        elif sc == "``":
            self.target.add_rendered("“", n.pos, end)
        elif sc == "''":
            self.target.add_rendered("”", n.pos, end)
        elif sc == "`":
            self.target.add_rendered("‘", n.pos, end)
        elif sc == "---":
            self.target.add_rendered("—", n.pos, end)
        elif sc == "--":
            self.target.add_rendered("–", n.pos, end)
        else:
            self.target.add_source(self.src[n.pos : end], n.pos)

    # -- math ------------------------------------------------------------
    def visit_math(self, n) -> None:
        d = n.delimiters or ("", "")
        display = d[0] in ("\\[", "$$")
        bs, be = n.pos + len(d[0]), n.pos + n.len - len(d[1] or "")
        self.doc.maths.append(MathInfo(n.pos, n.pos + n.len, bs, be, display))
        self.mask(bs, be)
        self.target.add_rendered(PH_DISPLAY if display else PH_MATH, n.pos, n.pos + n.len)

    # -- macros ------------------------------------------------------------
    def visit_macro(self, n) -> None:
        name = n.macroname
        end = n.pos + n.len
        t = self.target
        defs = self.defs

        if name in db.SECTION_LEVELS:
            self.visit_heading(n)
            return
        if name in defs.ignored_macros:
            self.mask_args(n)
            t.add_rendered(PH_OTHER, n.pos, end)
            return
        if name == "par":
            self.paragraph_break(n.pos)
            return
        if name == "item":
            self.visit_item(n)
            return
        if name in db.REF_MACROS:
            keys = _split_keys(_arg_text(self.src, _last_mandatory(n)))
            self.doc.refs.append(Ref(name, keys, n.pos, end))
            self.mask_args(n)
            t.add_rendered(PH_REF, n.pos, end)
            return
        if name in db.CITE_MACROS:
            keys = _split_keys(_arg_text(self.src, _last_mandatory(n)))
            self.doc.cites.append(Ref(name, keys, n.pos, end))
            self.mask_args(n)
            if name != "nocite":
                t.add_rendered(PH_CITE, n.pos, end)
            return
        if name == "label":
            key = _arg_text(self.src, _last_mandatory(n)).strip()
            fi = len(self.doc.floats) - 1 if self.float_stack else None
            env = self.env_stack[-1] if self.env_stack else None
            self.doc.labels.append(Label(key, n.pos, end, env, fi))
            if self.float_stack:
                self.float_stack[-1].labels.append((key, n.pos, end))
            self.mask_args(n)
            return
        if name in ("href",):
            args = _args(n)
            if args and args[-2 if len(args) >= 2 else -1] is not None:
                u = args[-2]
                self.doc.code_spans.append((u.pos, u.pos + u.len))
                self.mask(u.pos, u.pos + u.len)
            text = args[-1] if args else None
            if text is not None:
                self.visit(text)
            return
        if name in db.CODE_MACROS:
            for a in _args(n):
                if a is not None and isinstance(a, lw.LatexCharsNode) or name == "texttt":
                    if a is not None:
                        self.doc.code_spans.append((a.pos, a.pos + a.len))
            self.mask_args(n)
            t.add_rendered(PH_CODE, n.pos, end)
            return
        if name in db.INCLUDE_MACROS:
            targets = [_arg_text(self.src, a).strip() for a in _mandatory_args(n)]
            if name == "input" and _mandatory_args(n) and not isinstance(_mandatory_args(n)[0], lw.LatexGroupNode):
                mm = re.match(r"\\input\s+([^\s{}%\\]+)", self.src[n.pos :])
                if mm:
                    targets = [mm.group(1)]
            if name in ("import", "subimport", "includefrom") and len(targets) >= 2:
                target = os.path.join(targets[0], targets[1])
            else:
                target = targets[-1] if targets else ""
            if target:
                for tgt in (_split_keys(target) if name == "includeonly" else [target]):
                    self.doc.includes.append(Include(name, tgt, n.pos, end))
                self.doc.events.append(Event("include", n.pos, target))
            self.mask_args(n)
            return
        if name in ("includegraphics", "includesvg", "includepdf"):
            path = _arg_text(self.src, _last_mandatory(n)).strip()
            g = (path, n.pos, end)
            self.doc.graphics.append(g)
            if self.float_stack:
                self.float_stack[-1].graphics.append(g)
                self.float_stack[-1].content_positions.append(n.pos)
            self.mask_args(n)
            t.add_rendered(PH_OTHER, n.pos, end)
            return
        if name in db.BOLD_MACROS:
            self.doc.bold.append(MacroUse(name, n.pos, end, tuple(self.env_stack)))
        if name in db.COLOR_MACROS:
            self.doc.color.append(MacroUse(name, n.pos, end, tuple(self.env_stack)))
        if name in ("hline", "cline") and self.tabular_stack:
            self.tabular_stack[-1].hlines.append((n.pos, end))
        if name in ("fbox", "framebox", "frame") and self.float_stack:
            self.float_stack[-1].has_frame = True
        if name in db.FOOTNOTE_MACROS:
            arg = _last_mandatory(n)
            if arg is not None:
                b = self.sub_block("footnote", n.pos, macro=name)
                self.with_target(b, arg)
                self.finish_sub(b, end)
            return
        if name in db.CAPTION_MACROS:
            self.visit_caption(n)
            return
        if name in db.TITLE_MACROS:
            arg = _last_mandatory(n)
            if arg is not None:
                b = self.sub_block("title", n.pos, macro=name)
                self.with_target(b, arg)
                self.finish_sub(b, end)
            return
        if name in db.SIUNITX_NUMBER_MACROS or name in db.SIUNITX_UNIT_MACROS:
            self.visit_siunitx(n)
            return
        if name in db.TEXT_ARG_MACROS and db.TEXT_ARG_MACROS[name] is not None:
            arg = _last_mandatory(n)
            if name == "foreignlanguage" or name not in db.QUOTE_MACROS:
                if arg is not None:
                    self.visit(arg)
                return
            t.add_rendered("“", n.pos, arg.pos + 1 if arg is not None else end)
            if arg is not None:
                self.visit(arg)
            t.add_rendered("”", end - 1, end)
            return
        if name in db.SPACE_MACROS:
            if name in ("hspace",):
                self.mask_args(n)
            t.add_rendered(db.SPACE_MACROS[name], n.pos, end)
            return
        if name in db.SYMBOL_MACROS:
            t.add_rendered(db.SYMBOL_MACROS[name], n.pos, end)
            return
        if name in defs.text_macros:
            t.add_rendered(defs.text_macros[name], n.pos, end)
            return
        if name in db.SKIP_MACROS:
            self.mask_args(n)
            if name in ("newcommand", "renewcommand", "providecommand", "DeclareRobustCommand", "def", "newenvironment", "renewenvironment"):
                # mask the definition body that may follow as sibling groups
                pass
            return
        if name in db.EMPTY_MACROS:
            return
        kind = defs.macro_kinds.get(name)
        if kind is not None:
            if kind == "text":
                for a in _mandatory_args(n):
                    self.visit(a)
                return
            self.mask_args(n)
            ph = {"code": PH_CODE, "ref": PH_REF, "cite": PH_CITE}.get(kind)
            if ph:
                t.add_rendered(ph, n.pos, end)
            if kind == "code":
                for a in _mandatory_args(n):
                    self.doc.code_spans.append((a.pos, a.pos + a.len))
            return
        # unknown or accent macro: let latex2text render it
        try:
            text = _l2t.nodelist_to_text([n])
        except Exception:  # pragma: no cover - defensive
            text = ""
        if text.strip():
            t.add_rendered(text, n.pos, end)
        else:
            t.add_rendered(PH_OTHER, n.pos, end)
            # arguments known to the parser (e.g. \textcolor-like user macros)
            for a in _mandatory_args(n):
                self.visit(a)

    def with_target(self, b: _Builder, node) -> None:
        saved_target, saved_para = self.target, self.para
        self.target = b
        self.para = b  # paragraph breaks stay inside the sub-block
        try:
            self.visit(node)
        finally:
            self.target, self.para = saved_target, saved_para

    def visit_heading(self, n) -> None:
        end = n.pos + n.len
        level = db.SECTION_LEVELS[n.macroname]
        self.close_para(n.pos, "heading", "paragraph", "heading")
        b = self.sub_block("heading", n.pos, level=level, macro=n.macroname)
        arg = _last_mandatory(n)
        if arg is not None:
            self.with_target(b, arg)
        block = self.finish_sub(b, end)
        h = Heading(level, n.macroname, _is_star(n), block, n.pos, end)
        self.doc.headings.append(h)
        self.doc.events.append(Event("heading", n.pos, h))
        self.para.pos = end
        self.para.start_reason = "heading"

    def visit_item(self, n) -> None:
        end = n.pos + n.len
        if self.target is self.para:
            self.close_para(n.pos, "item", "item", "item")
            self.para.pos = end
        for a in _optional_args(n):
            self.visit(a)

    def visit_caption(self, n) -> None:
        end = n.pos + n.len
        arg = _last_mandatory(n)
        b = self.sub_block("caption", n.pos, macro=n.macroname)
        if arg is not None:
            self.with_target(b, arg)
        block = self.finish_sub(b, end)
        if self.float_stack:
            f = self.float_stack[-1]
            f.captions.append(block)
            f.caption_positions.append(n.pos)

    def visit_siunitx(self, n) -> None:
        end = n.pos + n.len
        name = n.macroname
        mand = _mandatory_args(n)
        t = self.target
        if name in db.SIUNITX_UNIT_MACROS:
            self.mask_args(n)
            t.add_rendered(PH_UNIT, n.pos, end)
            return
        nums = mand[:-1] if name in ("SI", "qty", "SIrange", "qtyrange", "SIlist", "qtylist") else mand
        for k, a in enumerate(nums):
            if k:
                t.add_rendered(" ", a.pos, a.pos)
            sp = _arg_inner_span(a)
            if sp:
                t.add_source(self.src[sp[0] : sp[1]], sp[0])
        if len(nums) < len(mand):
            u = mand[-1]
            t.add_rendered("\u00a0" + PH_UNIT, u.pos, u.pos + u.len)
        self.mask_args(n)

    # -- environments --------------------------------------------------------
    def env_body_span(self, n) -> tuple[int, int]:
        name = n.environmentname
        begin_tag = "\\begin{%s}" % name
        s = self.src.find(begin_tag, n.pos)
        bs = (s + len(begin_tag)) if s >= 0 else n.pos
        for a in _args(n):
            if a is not None and a.pos + a.len > bs and not (name in self.verbatim_envs and a is _args(n)[-1]):
                bs = a.pos + a.len
        e = self.src.rfind("\\end", n.pos, n.pos + n.len)
        be = e if e >= bs else n.pos + n.len
        return bs, be

    def mask_env_name(self, n) -> None:
        name = n.environmentname
        s = self.src.find("{", n.pos)
        if s >= 0:
            self.mask(s + 1, s + 1 + len(name))
        e = self.src.rfind("\\end", n.pos, n.pos + n.len)
        if e >= 0:
            s2 = self.src.find("{", e)
            if s2 >= 0:
                self.mask(s2 + 1, s2 + 1 + len(name))

    def visit_env(self, n) -> None:
        name = n.environmentname
        end = n.pos + n.len
        self.mask_env_name(n)

        if name in db.REMOVED_ENVS:
            self.doc.removed_spans.append((n.pos, end))
            return
        if name in self.verbatim_envs:
            bs, be = self.env_body_span(n)
            self.doc.code_spans.append((bs, be))
            self.mask(bs, be)
            if self.float_stack:
                self.float_stack[-1].content_positions.append(n.pos)
                return
            self.close_para(n.pos, "env", "paragraph", "continuation")
            self.doc.events.append(Event("code", n.pos, name))
            return
        if name in db.MATH_ENVS:
            bs, be = self.env_body_span(n)
            self.doc.maths.append(MathInfo(n.pos, end, bs, be, True, name))
            self.mask(bs, be)
            for lab in re.finditer(r"\\label\s*\{([^}]*)\}", self.src[bs:be]):
                fi = len(self.doc.floats) - 1 if self.float_stack else None
                self.doc.labels.append(Label(lab.group(1).strip(), bs + lab.start(), bs + lab.end(), name, fi))
            for ref in re.finditer(r"\\(%s)\*?\s*\{([^}]*)\}" % "|".join(sorted(db.REF_MACROS)), self.src[bs:be]):
                self.doc.refs.append(Ref(ref.group(1), _split_keys(ref.group(2)), bs + ref.start(), bs + ref.end()))
            self.target.add_rendered(PH_DISPLAY, n.pos, end)
            return
        if name in self.skip_envs:
            bs, be = self.env_body_span(n)
            self.mask(bs, be)
            if self.float_stack:
                self.float_stack[-1].content_positions.append(n.pos)
                # still pick up captions/labels inside (e.g. algorithmic)
                return
            if name != "thebibliography":
                self.close_para(n.pos, "env", "paragraph", "continuation")
                self.doc.events.append(Event("code", n.pos, name))
            return
        if name in db.FLOAT_ENVS and not (name in ("subfigure", "subtable") and self.float_stack):
            self.visit_float(n)
            return
        if name in db.TABULAR_ENVS or (name == "array" and not self.doc.in_math(n.pos)):
            self.visit_tabular(n)
            return
        if name in db.LIST_ENVS:
            self.visit_list_env(n)
            return
        if name in db.DOCUMENT_ENVS:
            self.env_stack.append(name)
            self.close_para(n.pos, "env", "paragraph", "start")
            self.in_preamble = False
            self.visit_list(_nodes(n))
            self.close_para(end, "eof", "paragraph", "end")
            self.env_stack.pop()
            return
        # generic block environment (quote, center, theorem, abstract, minipage...)
        self.env_stack.append(name)
        if self.float_stack or self.target is not self.para:
            self.visit_list(_nodes(n))
            self.env_stack.pop()
            return
        outer_kind = self.para.kind
        self.close_para(n.pos, "env", outer_kind if outer_kind != "paragraph" else "paragraph", "env-begin")
        for a in _optional_args(n):
            if name in ("theorem", "lemma", "definition", "proposition", "corollary", "remark", "example", "proof"):
                self.visit(a)
        self.visit_list(_nodes(n))
        self.env_stack.pop()
        self.close_para(end, "env-end", self.flow_kind(), "continuation")

    def visit_float(self, n) -> None:
        name = n.environmentname
        end = n.pos + n.len
        f = FloatInfo(name, n.pos, end)
        for a in _optional_args(n):
            f.placement = _arg_text(self.src, a).strip()
            f.placement_pos = a.pos
            break
        self.doc.floats.append(f)
        self.doc.events.append(Event("float", n.pos, f))
        self.float_stack.append(f)
        self.env_stack.append(name)
        saved_target, saved_para = self.target, self.para
        b = self.sub_block("float-text", n.pos)
        self.target = self.para = b
        try:
            self.visit_list(_nodes(n))
        finally:
            self.target, self.para = saved_target, saved_para
            self.env_stack.pop()
            self.float_stack.pop()
        if not b.empty():
            self.finish_sub(b, end)

    def visit_tabular(self, n) -> None:
        name = n.environmentname
        end = n.pos + n.len
        mand = _mandatory_args(n)
        colarg = mand[-1] if mand else None
        if name in ("tabular*", "tabularx", "tabulary") and len(mand) >= 2:
            colarg = mand[1]
        colspec = _arg_text(self.src, colarg) if colarg is not None else None
        info = TabularInfo(name, n.pos, end, colspec, colarg.pos if colarg is not None else None, in_float=bool(self.float_stack))
        self.doc.tabulars.append(info)
        for a in _args(n):
            sp = _arg_inner_span(a)
            if sp:
                self.mask(*sp)
        if self.float_stack:
            self.float_stack[-1].tabulars.append(info)
            self.float_stack[-1].content_positions.append(n.pos)
        else:
            self.doc.events.append(Event("tabular", n.pos, info))
        self.tabular_stack.append(info)
        self.env_stack.append(name)
        saved_target, saved_para = self.target, self.para
        b = self.sub_block("cell", n.pos)
        self.target = self.para = b
        try:
            for c in _nodes(n):
                if isinstance(c, lw.LatexMacroNode) and c.macroname == "\\":
                    b.add_rendered(PH_SEP, c.pos, c.pos + c.len)
                    continue
                self.visit(c)
        finally:
            self.target, self.para = saved_target, saved_para
            self.env_stack.pop()
            self.tabular_stack.pop()
        if not b.empty():
            self.finish_sub(b, end)

    def visit_list_env(self, n) -> None:
        name = n.environmentname
        end = n.pos + n.len
        if self.float_stack or (self.target is not self.para):
            self.list_depth += 1
            self.env_stack.append(name)
            self.visit_list(_nodes(n))
            self.env_stack.pop()
            self.list_depth -= 1
            return
        outer_kind = self.para.kind
        self.close_para(n.pos, "list", "item", "list")
        self.doc.events.append(Event("list", n.pos, name))
        self.list_depth += 1
        self.env_stack.append(name)
        self.visit_list(_nodes(n))
        self.env_stack.pop()
        self.list_depth -= 1
        self.close_para(end, "list-end", self.flow_kind() if outer_kind == "paragraph" else outer_kind, "continuation")


def _split_keys(s: str) -> list[str]:
    return [k.strip() for k in s.split(",") if k.strip()]


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _build_source_view(doc: Document) -> View:
    src = doc.source
    n = len(src)
    state = bytearray(n)  # 0 keep, 1 mask, 2 remove
    for a, b in doc.masked_spans:
        for i in range(max(a, 0), min(b, n)):
            if state[i] == 0:
                state[i] = 1
    for a, b in doc.comment_spans:
        # a line holding only a comment disappears entirely, newline included
        ls = src.rfind("\n", 0, a) + 1
        if src[ls:a].strip() == "" and b < n:
            a, b = ls, b + 1
        for i in range(a, min(b, n)):
            state[i] = 2
    for a, b in doc.removed_spans:
        for i in range(a, min(b, n)):
            if src[i] != "\n":
                state[i] = 2
    chars: list[str] = []
    offs: list[int] = []
    for i, c in enumerate(src):
        st = state[i]
        if st == 2:
            continue
        if st == 1 and c != "\n":
            chars.append(MASK)
        else:
            chars.append(c)
        offs.append(i)
    return View("".join(chars), offs)


def _build_prose_view(doc: Document) -> None:
    chars: list[str] = []
    offs: list[int] = []
    starts: list[int] = []
    for b in doc.blocks:
        starts.append(len(chars))
        chars.extend(b.text)
        offs.extend(b.starts)
        chars.append(BLOCK_SEP)
        offs.append(b.end)
    doc.prose = View("".join(chars), offs)
    doc._prose_block_starts = starts


# ---------------------------------------------------------------------------
# Language guess
# ---------------------------------------------------------------------------

_FR_WORDS = frozenset("le la les des est une du et pour dans que qui sur pas au aux avec ce cette nous sont être".split())
_EN_WORDS = frozenset("the of and is to in that for are with this on we be by as it an not".split())


def guess_language(text: str) -> str | None:
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 20:
        return None
    fr = sum(w in _FR_WORDS for w in words)
    en = sum(w in _EN_WORDS for w in words)
    if fr == en == 0:
        return None
    return "fr" if fr > en else "en"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse(path: str, source: str, defs: Definitions | None = None) -> Document:
    """Parse ``source`` (the content of ``path``) into a Document."""
    if defs is None:
        defs = db.scan_definitions(source)
    doc = Document(path, source)
    walker = _Walker(doc, defs)
    try:
        w = lw.LatexWalker(source, latex_context=make_context(defs), tolerant_parsing=True)
        nodes, _, _ = w.get_latex_nodes()
    except Exception as e:  # tolerant parsing rarely fails, but be safe
        doc.parse_errors.append((0, str(e)))
        nodes = [lw.LatexCharsNode(chars=source, pos=0, len=len(source), parsing_state=None)]
    walker.visit_list(nodes or [])
    walker.close_para(len(source), "eof", "paragraph", "end")
    doc.events.append(Event("eof", len(source)))
    doc.blocks.sort(key=lambda b: (b.starts[0] if b.starts else b.pos))
    doc.source_view = _build_source_view(doc)
    _build_prose_view(doc)
    doc.language = doc.declared_language or guess_language(doc.prose.text) or "en"
    return doc
