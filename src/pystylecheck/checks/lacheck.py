"""Checks inspired by lacheck, with its false positives removed.

lacheck scans character by character, has no math mode, treats only the
verbatim environment as verbatim and knows nothing about \\frenchspacing,
\\makeatletter or LaTeX2e fonts. These versions run on the parsed document,
so they skip code, comments and math where it matters.
"""

from __future__ import annotations

import os
import re

from ..latexdb import PH_DISPLAY, PLACEHOLDERS
from . import Check, register


def _english_spacing(doc, ctx) -> bool:
    return doc.language == "en" and not doc.frenchspacing and not ctx.opt("frenchspacing", False)


def _body_start(doc) -> int:
    i = doc.source.find("\\begin{document}")
    return i if doc.is_root and i >= 0 else 0


def _visible(doc, a: int, b: int | None = None) -> bool:
    """True if [a, b) is ordinary LaTeX: not a comment, code or a removed region."""
    b = a + 1 if b is None else b
    return not any(doc.in_comment(o) or doc.in_code(o) for o in (a, max(a, b - 1)))


@register
class CapitalSentenceEnd(Check):
    id = "capital-sentence-end"
    description = "A sentence ending with a capital letter needs \\@ before the period (NASA\\@. The)"
    explanation = (
        "With English spacing, TeX assumes a period after a capital letter ends an abbreviation, "
        "not a sentence, and uses a normal space. Write 'NASA\\@. The' to get the sentence space. "
        "Not needed with \\frenchspacing or in French."
    )
    category = "typography"
    severity = "warning"
    languages = frozenset(["en"])
    origin = "lacheck"
    fixable = True

    def check(self, doc, ctx):
        if not _english_spacing(doc, ctx):
            return
        sv = doc.source_view
        for m in re.finditer(r"(?<![\\\w])([A-Z]{2,})([.!?])(?=(?:[ \t]+\n?|\n)[ \t]*[A-Z])", sv.text):
            s, e = sv.src_span(m.start(2), m.end(2))
            if doc.source[s - 2 : s] == "\\@" or not _visible(doc, s):
                continue
            yield ctx.make(self, doc, s, e, f"write '{m.group(1)}\\@{m.group(2)}' so that TeX sees the end of the sentence",
                           replacement="\\@" + m.group(2))


@register
class DoubleSpace(Check):
    id = "double-space"
    description = "Two spaces in a row from ~ (~~, ~ at the end of a line)"
    explanation = "'~~' or a '~' at the end of a line followed by text prints two spaces."
    category = "typography"
    severity = "warning"
    origin = "lacheck"

    def check(self, doc, ctx):
        sv = doc.source_view
        for m in re.finditer(r"(?<!\\)~~|(?<!\\)~[ \t]*\n(?=[ \t]*[^\s%\\])|\\space[ \t]*~|~\\space\b", sv.text):
            s, e = sv.src_span(m.start(), m.end())
            if not _visible(doc, s) or doc.in_math(s):
                continue
            yield ctx.make(self, doc, s, e, "double space: the ~ is next to another space")


@register
class Ellipsis(Check):
    id = "ellipsis"
    description = "Write \\dots (or …) rather than three periods"
    explanation = "Three periods are spaced too tightly and may break across lines: use \\dots (or \\ldots)."
    category = "typography"
    severity = "warning"
    origin = "lacheck"
    fixable = True

    def check(self, doc, ctx):
        for b in doc.prose_blocks("paragraph", "item", "footnote", "caption", "heading", "title", "cell"):
            for m in re.finditer(r"(?<!\.)\.\.\.(?!\.)", b.text):
                if not b.is_verbatim(doc.source, m.start(), m.end()):
                    continue
                yield ctx.at_prose(self, doc, b, m.start(), m.end(), "use \\dots instead of '...'", replacement="\\dots")


_BIN = r"(?:[-+=<>]|\\cdot|\\times|\\oplus|\\otimes|\\leq?|\\geq?|\\ne|\\equiv|\\cup|\\cap|\\wedge|\\vee)"
_SP = r"(?:\s|\\[,;:!]|\\quad)*"


@register
class MathDots(Check):
    id = "math-dots"
    description = "In math: \\cdots between operators (a + \\cdots + b), \\ldots between commas (a, \\ldots, b)"
    explanation = (
        "Centered dots go between binary operators (x_1 + \\cdots + x_n), low dots between commas "
        "(x_1, \\ldots, x_n). Literal '...' in math should be \\dots. amsmath's \\dots chooses for you."
    )
    category = "math"
    severity = "warning"
    origin = "lacheck"

    def check(self, doc, ctx):
        src = doc.source
        for mi in doc.maths:
            body = src[mi.body_start : mi.body_end]
            for m in re.finditer(r"(?<!\.)\.\.\.(?!\.)", body):
                s = mi.body_start + m.start()
                yield ctx.make(self, doc, s, s + 3, "use \\dots (\\ldots or \\cdots) in math, not '...'")
            for m in re.finditer(_BIN + _SP + r"(\\ldots)" + _SP + _BIN, body):
                s = mi.body_start + m.start(1)
                yield ctx.make(self, doc, s, s + 6, "between operators, use \\cdots (or \\dots with amsmath)", replacement="\\cdots")
            for m in re.finditer(r"(?<!\\),\s*(?:\\[,;:!]\s*)*(\\cdots)\s*(?:\\[,;:!]\s*)*,", body):
                s = mi.body_start + m.start(1)
                yield ctx.make(self, doc, s, s + 6, "between commas, use \\ldots (or \\dots with amsmath)", replacement="\\ldots")


@register
class MathPunctuationPlacement(Check):
    id = "math-punctuation"
    description = "Sentence punctuation goes outside inline math ($x$.) and inside displayed math"
    explanation = (
        "Write '$x$.' rather than '$x.$': the period belongs to the sentence, not to the formula. "
        "For a displayed formula it is the opposite: the period goes inside, before \\] or \\end{equation}."
    )
    category = "math"
    severity = "warning"
    origin = "lacheck"

    def check(self, doc, ctx):
        src = doc.source
        for mi in doc.maths:
            if mi.display:
                m = re.match(r"[ \t]*([.,;!?])", src[mi.end : mi.end + 4])
                if m and not src.startswith("..", mi.end + m.start(1)):
                    s = mi.end + m.start(1)
                    yield ctx.make(self, doc, s, s + 1, f"move '{m.group(1)}' inside the displayed formula")
            else:
                body = src[mi.body_start : mi.body_end]
                m = re.search(r"([.?])\s*$", body)
                if not m or re.fullmatch(r"\s*[\d.]+\s*", body) or re.search(r"\\[a-z]*dots\s*\.?\s*$|\.\.\s*$", body):
                    continue
                s = mi.body_start + m.start(1)
                yield ctx.make(self, doc, s, s + 1, f"put '{m.group(1)}' after the closing $: '$...$' then the punctuation")


@register
class FootnoteSpace(Check):
    id = "footnote-space"
    description = "No space before \\footnote"
    explanation = "A space before \\footnote ends up between the word and the footnote mark."
    category = "latex"
    severity = "error"
    origin = "lacheck"
    fixable = True

    def check(self, doc, ctx):
        sv = doc.source_view
        for m in re.finditer(r"(?<=[^\s~{}])([ \t]+\n?[ \t]*|\n[ \t]*)\\footnote\b(?!mark|text)", sv.text):
            s, e = sv.src_span(m.start(1), m.end(1))
            if "%" in doc.source[s:e] or not _visible(doc, s):
                continue
            yield ctx.make(self, doc, s, e, "no space before \\footnote", replacement="")


@register
class LabelCharacters(Check):
    id = "label-characters"
    description = "Labels should not contain spaces or special characters"
    explanation = "Characters such as space, #, $, %, ^, &, ~, {, \", <, > in \\label keys break some packages."
    category = "reference"
    severity = "warning"
    origin = "lacheck"

    def check(self, doc, ctx):
        for lab in doc.labels:
            if re.search(r"[#$%^&*+={}~\"<>\s\\]", lab.key):
                yield ctx.make(self, doc, lab.pos, lab.end, f"bad character in label '{lab.key}'")


_PRIMITIVES = {
    "vskip": "\\vspace",
    "hskip": "\\hspace",
    "advance": "\\addtocounter or \\addtolength",
    "count": "a LaTeX counter",
    "catcode": None,
    "chardef": None,
    "countdef": "\\newcounter",
    "dimendef": "\\newlength",
    "csname": None,
    "expandafter": None,
    "font": "\\fontsize/\\selectfont",
    "openout": None,
    "closeout": None,
    "closein": None,
    "divide": None,
    "above": "\\frac",
    "over": "\\frac",
    "centerline": "\\centering or \\begin{center}",
    "obeylines": None,
}


@register
class TexPrimitive(Check):
    id = "tex-primitive"
    description = "Plain TeX primitives in the document body (\\vskip, \\over, \\centerline...)"
    explanation = "In the body of a LaTeX document, prefer the LaTeX commands: \\vspace over \\vskip, \\frac over \\over."
    category = "latex"
    severity = "warning"
    origin = "lacheck"

    def check(self, doc, ctx):
        if doc.path.endswith((".sty", ".cls")):
            return
        body = _body_start(doc)
        rx = re.compile(r"\\(%s)(?![A-Za-z@])" % "|".join(_PRIMITIVES))
        sv = doc.source_view
        for m in rx.finditer(sv.text):
            s, e = sv.src_span(m.start(), m.end())
            if s < body or not _visible(doc, s) or (doc.in_math(s) and m.group(1) not in ("over", "above")):
                continue
            alt = _PRIMITIVES[m.group(1)]
            hint = f": use {alt}" if alt else ""
            yield ctx.make(self, doc, s, e, f"avoid the TeX primitive \\{m.group(1)} in a LaTeX document{hint}")


_OLD_FONTS = {"bf": "\\textbf{...}", "it": "\\textit{...}", "sl": "\\textsl{...}", "tt": "\\texttt{...}", "rm": "\\textrm{...}",
              "sf": "\\textsf{...}", "sc": "\\textsc{...}", "em": "\\emph{...}"}


@register
class FontSwitchArgument(Check):
    id = "font-switch"
    description = "\\bf, \\it, \\tt... are obsolete and take no argument: use \\textbf{}, \\textit{}, \\emph{}"
    explanation = (
        "'\\bf{text}' does not do what it seems: \\bf switches the font until the end of the group "
        "and takes no argument. The two-letter commands are obsolete in LaTeX2e anyway."
    )
    category = "latex"
    severity = "warning"
    origin = "lacheck"

    def check(self, doc, ctx):
        sv = doc.source_view
        body = _body_start(doc)
        for m in re.finditer(r"(.)?\\(bf|it|sl|tt|rm|sf|sc|em)(?![A-Za-z@])([ \t]*\{)?", sv.text):
            s, e = sv.src_span(m.start(2) - 1, m.end(2))
            if s < body or not _visible(doc, s) or doc.in_math(s):
                continue
            alt = _OLD_FONTS[m.group(2)]
            if m.group(3) and m.group(1) != "{":
                yield ctx.make(self, doc, s, e, f"\\{m.group(2)} takes no argument: write {alt}", severity="error")
            elif m.group(2) != "em":
                yield ctx.make(self, doc, s, e, f"\\{m.group(2)} is obsolete in LaTeX2e: use {alt}")


@register
class AtInMacroName(Check):
    id = "at-in-macro"
    description = "@ in macro names outside \\makeatletter ... \\makeatother"
    explanation = "In a .tex file, @ is not a letter: \\foo@bar is read as \\foo followed by '@bar' unless \\makeatletter is active."
    category = "latex"
    severity = "error"
    origin = "lacheck"

    def check(self, doc, ctx):
        if doc.path.endswith((".sty", ".cls", ".dtx")):
            return
        src = doc.source
        regions = []
        for m in re.finditer(r"\\makeatletter\b", src):
            e = src.find("\\makeatother", m.end())
            regions.append((m.start(), e if e >= 0 else len(src)))
        sv = doc.source_view
        for m in re.finditer(r"\\([A-Za-z@]*@[A-Za-z@]+|[A-Za-z]+@[A-Za-z@]*)", sv.text):
            s, e = sv.src_span(m.start(), m.end())
            if any(a <= s < b for a, b in regions) or not _visible(doc, s):
                continue
            if re.fullmatch(r"\\@+", src[s:e]):
                continue
            # inside a definition body (\newcommand, \def...) the author probably knows what they do
            ls = src.rfind("\n", 0, s) + 1
            if re.search(r"\\(?:re)?newcommand|\\def\b|\\providecommand|\\let\b|\\DeclareRobustCommand", src[ls:s]):
                continue
            yield ctx.make(self, doc, s, e, f"'{src[s:e]}' uses @ outside \\makeatletter ... \\makeatother")


@register
class QuoteDirection(Check):
    id = "quote-direction"
    description = "Use `` to open and '' to close quotations"
    explanation = "In LaTeX, `` opens and '' closes a quotation. ''word or word`` are reversed."
    category = "typography"
    severity = "warning"
    origin = "lacheck"

    def check(self, doc, ctx):
        for b in doc.prose_blocks("paragraph", "item", "footnote", "caption", "heading", "title", "cell"):
            t = b.text
            for m in re.finditer(r"(?:^|(?<=[\s\u00a0(\[]))”(?=[^\W\d_])", t):
                yield ctx.at_prose(self, doc, b, m.start(), m.end(), "'' closes a quotation: use `` to open it")
            for m in re.finditer(r"(?<=[^\W\d_])[“‘](?=[\s\u00a0.,;:!?)]|$)", t):
                yield ctx.at_prose(self, doc, b, m.start(), m.end(), "` opens a quotation: use ' to close it")


@register
class BeginEndArgument(Check):
    id = "begin-end-argument"
    description = "\\begin and \\end need their {environment} argument on the same line"
    category = "latex"
    severity = "error"
    origin = "lacheck"

    def check(self, doc, ctx):
        sv = doc.source_view
        for m in re.finditer(r"\\(begin|end)(?![A-Za-z@])[ \t]*(?:\n|$|(?=[^{\s\[]))", sv.text):
            s, e = sv.src_span(m.start(), m.start() + len(m.group(1)) + 1)
            if not _visible(doc, s):
                continue
            yield ctx.make(self, doc, s, e, f"{{argument}} missing for \\{m.group(1)}")


@register
class VerbNewline(Check):
    id = "verb-newline"
    description = "\\verb must end on the same line; no tabs in verbatim"
    category = "latex"
    severity = "error"
    origin = "lacheck"

    def check(self, doc, ctx):
        src = doc.source
        for m in re.finditer(r"\\verb\*?([^A-Za-z\s*])", src):
            if doc.in_comment(m.start()) or any(a <= m.start() < b for a, b in doc.code_spans):
                continue
            d = m.group(1)
            close = src.find(d, m.end())
            nl = src.find("\n", m.end())
            if close < 0 or (0 <= nl < close):
                yield ctx.make(self, doc, m.start(), m.end(), "\\verb should not contain end of line characters")
        for m in re.finditer(r"\\begin\{verbatim\}(.*?)\\end\{verbatim\}", src, re.S):
            for t in re.finditer("\t", m.group(1)):
                p = m.start(1) + t.start()
                yield ctx.make(self, doc, p, p + 1, "TAB character in verbatim environment: it prints as a single space",
                               severity="warning")
                break


@register
class ItalicCorrection(Check):
    id = "italic-correction"
    description = "Misplaced italic corrections: no \\/ before a period or comma, no double \\/"
    explanation = "The italic correction \\/ is not wanted before '.' or ',', and \\textit/\\emph add it automatically."
    category = "typography"
    severity = "warning"
    origin = "lacheck"

    def check(self, doc, ctx):
        sv = doc.source_view
        for m in re.finditer(r"\\/(\s*\}?\s*)([.,])|\\/\s*\\/", sv.text):
            s, e = sv.src_span(m.start(), m.end())
            if not _visible(doc, s):
                continue
            msg = "double \\/" if m.group(0).count("\\/") == 2 else f"do not use \\/ before '{m.group(2)}'"
            yield ctx.make(self, doc, s, e, msg)


@register
class SpaceInTextArgument(Check):
    id = "space-after-brace"
    description = "Unwanted space at the start of \\emph{ ...}, \\textbf{ ...}"
    explanation = "'\\emph{ word}' prints a space inside the emphasis, often doubling the space before it."
    category = "typography"
    severity = "warning"
    origin = "lacheck"
    fixable = True

    def check(self, doc, ctx):
        sv = doc.source_view
        rx = re.compile(r"\\(emph|textit|textbf|textsc|textsf|textrm|textsl|underline|mbox|enquote)\{([ \t]+)(?=\S)")
        for m in rx.finditer(sv.text):
            s, e = sv.src_span(m.start(2), m.end(2))
            if _visible(doc, s):
                yield ctx.make(self, doc, s, e, f"unwanted space at the start of \\{m.group(1)}{{...}}", replacement="")


@register
class Unbalanced(Check):
    id = "unbalanced"
    description = "Unbalanced \\begin/\\end, braces or $ (lacheck's mismatch report)"
    explanation = (
        "Every \\begin{x} needs a matching \\end{x}, braces must balance within a file and inline "
        "math $ must be closed within the paragraph. Definitions, comments and verbatim text are ignored."
    )
    category = "latex"
    severity = "error"
    origin = "lacheck"

    def check(self, doc, ctx):
        src = doc.source
        n = len(src)
        skip = bytearray(n)
        for a, b in doc.comment_spans + doc.removed_spans + doc.code_spans:
            for i in range(max(0, a), min(b, n)):
                skip[i] = 1
        # definition bodies may legitimately hold half an environment
        for m in re.finditer(r"\\(?:re)?newenvironment\*?\s*\{[^}]*\}\s*(?:\[\d\])?\s*(?:\[[^\]]*\])?", src):
            p = m.end()
            for _ in range(2):
                while p < n and src[p] in " \t\n":
                    p += 1
                if p < n and src[p] == "{":
                    e = _match_brace(src, p)
                    for i in range(p, e):
                        skip[i] = 1
                    p = e
        for m in re.finditer(r"\\(?:re)?(?:newcommand|providecommand|DeclareRobustCommand)\*?\s*(?:\{\\[^}]+\}|\\[A-Za-z@]+)\s*(?:\[\d\])?\s*(?:\[[^\]]*\])?\s*\{|\\[gex]?def\s*\\[A-Za-z@]+[^{\n]*\{", src):
            p = m.end() - 1
            e = _match_brace(src, p)
            for i in range(p + 1, max(p + 1, e - 1)):
                skip[i] = 1
        stack: list[tuple[str, int]] = []
        for m in re.finditer(r"\\(begin|end)\s*\{([^}]*)\}", src):
            if skip[m.start()]:
                continue
            name = m.group(2).strip()
            if m.group(1) == "begin":
                stack.append((name, m.start()))
            else:
                if stack and stack[-1][0] == name:
                    stack.pop()
                elif any(x[0] == name for x in stack):
                    while stack and stack[-1][0] != name:
                        nm, p = stack.pop()
                        yield ctx.make(self, doc, p, p + len(nm) + 8, f"\\begin{{{nm}}} is never closed (found \\end{{{name}}})")
                    stack.pop()
                else:
                    yield ctx.make(self, doc, m.start(), m.end(), f"\\end{{{name}}} without a matching \\begin{{{name}}}")
        for nm, p in stack:
            if nm != "document" or doc.is_root:
                yield ctx.make(self, doc, p, p + len(nm) + 8, f"\\begin{{{nm}}} is never closed")
        # braces
        depth = 0
        opens: list[int] = []
        i = 0
        while i < n:
            c = src[i]
            if skip[i]:
                i += 1
                continue
            if c == "\\":
                i += 2
                continue
            if c == "{":
                opens.append(i)
            elif c == "}":
                if opens:
                    opens.pop()
                else:
                    yield ctx.make(self, doc, i, i + 1, "unmatched '}'")
            i += 1
        for p in opens[:3]:
            yield ctx.make(self, doc, p, p + 1, "unmatched '{'")
        # inline math, per paragraph
        for para in re.finditer(r"(?:[^\n]|\n(?![ \t]*\n))+", src):
            count = 0
            first = None
            for d in re.finditer(r"(?<!\\)\$\$?", para.group(0)):
                p = para.start() + d.start()
                if skip[p] or len(d.group(0)) == 2:
                    continue
                count += 1
                first = p if first is None else first
            if count % 2 and first is not None:
                yield ctx.make(self, doc, first, first + 1, "unbalanced $ in this paragraph", severity="warning")


def _match_brace(src: str, p: int) -> int:
    depth = 0
    i = p
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            e = src.find("\n", i)
            i = len(src) if e < 0 else e
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(src)


@register
class MissingInclude(Check):
    id = "missing-include"
    description = "\\input or \\include of a file that cannot be found"
    category = "latex"
    severity = "info"
    origin = "lacheck"

    def check(self, doc, ctx):
        if doc.path.startswith("<"):
            return
        from ..engine import resolve_include

        base = os.path.dirname(os.path.abspath(doc.path))
        for inc in doc.includes:
            if inc.macro not in ("input", "include", "subfile") or "\\" in inc.target or "#" in inc.target:
                continue
            if inc.target.endswith((".bbl", ".toc", ".aux", ".sty", ".cls")) or os.path.splitext(inc.target)[1] in (".tikz", ".pgf", ".pdf_tex"):
                if resolve_include(base, inc.target) is None and not os.path.exists(os.path.join(base, inc.target)):
                    continue
            if resolve_include(base, inc.target) is None and not os.path.exists(os.path.join(base, inc.target)):
                yield ctx.make(self, doc, inc.pos, inc.end, f"could not find '{inc.target}' (relative to {os.path.basename(base) or base})")
