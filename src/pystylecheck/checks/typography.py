"""Typographic checks: quotes, spacing, units, numbers, emphasis."""

from __future__ import annotations

import re

from ..latexdb import FLOAT_ENVS, PH_UNIT, TABULAR_ENVS
from . import Check, register

UNITS = (
    r"kg|mg|µg|km|cm|mm|µm|nm|ms|µs|ns|ps|min|Hz|kHz|MHz|GHz|THz|kW|MW|GW|mW|kWh|kJ|MJ|kV|mV|mA|kA|"
    r"°C|°F|°|kB|KB|MB|GB|TB|PB|KiB|MiB|GiB|TiB|ko|Ko|Mo|Go|To|kb|Kb|Mb|Gb|Tb|bps|kbps|Mbps|Gbps|"
    r"px|dpi|ns/B|GB/s|MB/s|Go/s|Mo/s|km/h|m/s|GiB/s|Gbit/s"
)


def _prose_blocks(doc):
    return doc.prose_blocks("paragraph", "item", "footnote", "caption", "heading", "title", "cell")


@register
class StraightQuotes(Check):
    id = "straight-quotes"
    description = "Straight double quotes \"...\" in LaTeX source"
    explanation = (
        "LaTeX does not turn \" into curly quotes: write ``like this'' or use \\enquote{} (csquotes). "
        "In French, use \\enquote{} with babel-french to get « guillemets »."
    )
    category = "typography"
    severity = "warning"

    def check(self, doc, ctx):
        hint = "\\enquote{...}" if doc.language == "fr" else "``...'' or \\enquote{...}"
        for b in doc.prose_blocks("paragraph", "item", "footnote", "caption", "heading", "title"):
            for m in re.finditer(r'"', b.text):
                if not b.is_verbatim(doc.source, m.start(), m.end()):
                    continue
                s, _ = b.span(m.start(), m.end())
                if s > 0 and doc.source[s - 1] == "\\":
                    continue
                yield ctx.at_prose(self, doc, b, m.start(), m.end(), f"straight double quote: use {hint}")
            if doc.language == "en":
                for m in re.finditer(r"(?<![\w’'`])'(?=[^\W\d_])", b.text):
                    if b.is_verbatim(doc.source, m.start(), m.end()):
                        yield ctx.at_prose(self, doc, b, m.start(), m.end(), "use ` (backtick) for an opening single quote")


@register
class FrenchGuillemets(Check):
    id = "french-guillemets"
    description = "French quotes need non-breaking spaces inside: «~texte~»"
    explanation = (
        "In French, put a non-breaking space after « and before ». Better: use \\enquote{} from "
        "csquotes with babel-french, which spaces them automatically."
    )
    category = "typography"
    severity = "warning"
    languages = frozenset(["fr"])
    origin = "guide"

    def check(self, doc, ctx):
        for b in _prose_blocks(doc):
            t = b.text
            for m in re.finditer("«", t):
                nxt = t[m.end() : m.end() + 1]
                if nxt and nxt not in "  ":
                    yield ctx.at_prose(self, doc, b, m.start(), m.end() + (1 if nxt == " " else 0),
                                       "put a non-breaking space after «: «~ (or use \\enquote{})")
            for m in re.finditer("»", t):
                prv = t[m.start() - 1 : m.start()] if m.start() else ""
                if prv and prv not in "  ":
                    a = m.start() - (1 if prv == " " else 0)
                    yield ctx.at_prose(self, doc, b, a, m.end(), "put a non-breaking space before »: ~» (or use \\enquote{})")


@register
class UnitSpacing(Check):
    id = "unit-spacing"
    description = "Use a non-breaking space between a number and its unit (5~km, 12~\\%), or siunitx"
    explanation = (
        "A non-breaking space separates a value from its unit so that they stay on the same line: "
        "5~km, 250~ms. In French, the percent sign is also preceded by a non-breaking space (12~\\%). "
        "The siunitx package (\\qty{5}{\\km}, \\SI{5}{\\km}) does it for you."
    )
    category = "typography"
    severity = "warning"
    origin = "guide"
    fixable = True

    def check(self, doc, ctx):
        rx = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)([ \t]*\n?[ \t]*)(%s|%%)(?![\w/])" % UNITS)
        for b in _prose_blocks(doc):
            for m in rx.finditer(b.text):
                gap = m.group(2)
                if not b.is_verbatim(doc.source, m.start(1), m.end(3)):
                    # e.g. 12\% : the source is not a copy of the prose; check the gap only
                    if gap and not b.is_verbatim(doc.source, m.start(2), m.end(2)):
                        continue
                unit = m.group(3)
                if unit == "%":
                    if doc.language != "fr":
                        continue
                    if gap:
                        s, e = b.span(m.start(2), m.end(2))
                        yield ctx.make(self, doc, s, e, "use a non-breaking space before %: 12~\\%", replacement="~")
                    else:
                        s, e = b.span(m.end(1) - 1, m.end(3))
                        yield ctx.make(self, doc, s, e, "en français, une espace insécable précède %: 12~\\%",
                                       replacement=doc.source[s] + "~" + doc.source[s + 1 : e])
                    continue
                if not gap:
                    continue
                s, e = b.span(m.start(2), m.end(2))
                yield ctx.make(self, doc, s, e, f"use a non-breaking space between the number and the unit: {m.group(1)}~{unit}",
                               replacement="~")


_VERSION_CONTEXT = re.compile(
    r"(?:version|versions|v|release|python|java|gcc|clang|llvm|node|ubuntu|macos|ios|android|windows|"
    r"section|sections|sous-section|chapitre|chapter|figure|figures|tableau|table|équation|equation|"
    r"annexe|appendix|fig\.|tab\.|§|eq\.|éq\.|no\.|n°|ieee|iso|rfc|unicode|utf|c\+\+|ecmascript|es|"
    r"c|avx|sse|neon|armv|x86|arm|http|tls|ssl|ipv|level|niveau|algorithme|algorithm|line|ligne|step|étape|"
    r"doi|doi:|arxiv|isbn|issn|lemma|lemme|theorem|théorème|definition|définition|exemple|example|page|pages|p\.|pp\.)[\s ~-]*$",
    re.I,
)


def _numbers(text: str, decimal: str):
    sep = re.escape(decimal)
    return re.finditer(r"(?<![\w.,/:-])(\d+)%s(\d+)(?:[eE][+-]?\d+)?(?![\w/]|[.,]\d)" % sep, text)


@register
class DecimalSeparator(Check):
    id = "decimal-separator"
    description = "French uses a decimal comma: 3,14 not 3.14"
    explanation = "In French, the decimal separator is a comma. With siunitx, \\num{3.14} prints 3,14 under locale=FR."
    category = "typography"
    severity = "warning"
    languages = frozenset(["fr"])
    origin = "guide"
    fixable = True

    def check(self, doc, ctx):
        for b in _prose_blocks(doc):
            for m in _numbers(b.text, "."):
                if not b.is_verbatim(doc.source, m.start(), m.end()):
                    continue
                if _VERSION_CONTEXT.search(b.text[max(0, m.start() - 25) : m.start()]):
                    continue
                s, e = b.span(m.start(), m.end())
                if any(x for x in doc.maths if x.body_start <= s < x.body_end):
                    continue
                yield ctx.make(self, doc, s, e, f"en français, le séparateur décimal est la virgule: {m.group(0).replace('.', ',', 1)}",
                               replacement=m.group(0).replace(".", ",", 1))


@register
class SignificantDigits(Check):
    id = "significant-digits"
    description = "Measured values should have at most 3 significant digits (max_significant_digits)"
    explanation = (
        "Numerical values are presented with 1 to 3 significant digits: 1.2 s rather than 1.234 s, "
        "12 % rather than 12.312 %. Extra digits suggest a precision you do not have."
    )
    category = "typography"
    severity = "info"
    origin = "guide"

    def check(self, doc, ctx):
        limit = int(ctx.opt("max_significant_digits", 3))
        decimal = "," if doc.language == "fr" else "."
        for b in _prose_blocks(doc):
            hits = []
            for m in _numbers(b.text, decimal):
                if _VERSION_CONTEXT.search(b.text[max(0, m.start() - 25) : m.start()]):
                    continue
                digits = (m.group(1) + m.group(2)).lstrip("0")
                if len(digits) > limit:
                    hits.append((m, len(digits)))
            if not hits:
                continue
            if b.kind == "cell":
                m, n = hits[0]
                more = f" ({len(hits)} such values in this table)" if len(hits) > 1 else ""
                yield ctx.at_prose(self, doc, b, m.start(), m.end(),
                                   f"{m.group(0)} has {n} significant digits{more}: 1 to {limit} are usually enough")
                continue
            for m, n in hits:
                yield ctx.at_prose(self, doc, b, m.start(), m.end(),
                                   f"{m.group(0)} has {n} significant digits: 1 to {limit} are usually enough")


@register
class BoldText(Check):
    id = "bold-text"
    description = "Little or no bold in a scientific document"
    explanation = (
        "Scientific documents use little or no bold. Use italics (\\emph) to introduce a term or for "
        "emphasis. Bold in table headers is tolerated."
    )
    category = "typography"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        body = doc.source.find("\\begin{document}") if doc.is_root else 0
        for u in doc.bold:
            if u.pos < body or any(e in TABULAR_ENVS or e in FLOAT_ENVS or e in ("titlepage", "description", "frame") for e in u.envs):
                continue
            yield ctx.make(self, doc, u.pos, u.end if u.macro != "textbf" else u.pos + 7,
                           "avoid bold in running text: use \\emph{} for emphasis")


@register
class ColoredText(Check):
    id = "colored-text"
    description = "Text, including headings, is black"
    explanation = "The text of a document, including titles and subtitles, uses black ink. Color belongs in figures."
    category = "typography"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        body = doc.source.find("\\begin{document}") if doc.is_root else 0
        for u in doc.color:
            if u.pos < body or any(e in FLOAT_ENVS or e in ("tikzpicture", "frame") for e in u.envs):
                continue
            yield ctx.make(self, doc, u.pos, u.pos + len(u.macro) + 1, "text should be black: avoid colored text")


@register
class SpaceAroundTie(Check):
    id = "space-around-tie"
    description = "A space next to ~ produces a double space"
    explanation = "'Figure ~\\ref{x}' prints two spaces: the ~ already is a space."
    category = "typography"
    severity = "warning"
    fixable = True

    def check(self, doc, ctx):
        sv = doc.source_view
        for m in re.finditer(r"(?<=\S)([ \t]+)~|~([ \t]+)(?=\S)", sv.text):
            s, e = sv.src_span(m.start(), m.end())
            if doc.is_hidden(s) or "\n" in doc.source[s:e]:
                continue
            yield ctx.make(self, doc, s, e, "double space: remove the space next to ~", replacement="~")


_ABBR = r"e\.g|i\.e|etc|cf|vs|al|resp|approx|viz|Fig|Figs|Eq|Eqs|Sec|Secs|Ch|Chap|Dr|Prof|Mr|Mrs|Ms|St|No|Vol|pp|Thm|Def|Alg|Tab"
_TITLES = {"Fig", "Figs", "Eq", "Eqs", "Sec", "Secs", "Ch", "Chap", "Dr", "Prof", "Mr", "Mrs", "Ms", "St", "No", "Vol", "pp", "vs", "cf", "Thm", "Def", "Alg", "Tab"}


@register
class AbbreviationSpacing(Check):
    id = "abbreviation-spacing"
    description = "After an abbreviation inside a sentence, use '\\ ' or '~' (English spacing)"
    explanation = (
        "With English spacing, TeX puts a wider space after a period that follows a lowercase "
        "letter. Inside a sentence, write 'e.g.\\ this', 'et al.\\ show', 'Fig.~3'. Not needed "
        "with \\frenchspacing or in French."
    )
    category = "typography"
    severity = "warning"
    languages = frozenset(["en"])
    fixable = True

    def check(self, doc, ctx):
        if doc.frenchspacing or ctx.opt("frenchspacing", False):
            return
        sv = doc.source_view
        rx = re.compile(r"(?<![\w\\.])(%s)\.([ \t]+\n?[ \t]*|\n[ \t]*)(?=([a-z0-9(]|\\(?:cite|ref|eqref|citep?)\b|[A-Z]))" % _ABBR)
        for m in rx.finditer(sv.text):
            abbr = m.group(1)
            nxt = m.group(3)
            if nxt[0].isupper() and abbr not in _TITLES:
                continue  # probably the end of a sentence ("... etc. The")
            s, e = sv.src_span(m.start(2), m.end(2))
            if "%" in doc.source[s:e]:
                continue
            rep = "~" if abbr in _TITLES else "\\ "
            yield ctx.make(self, doc, s, e, f"after '{abbr}.' inside a sentence, write '{abbr}.{rep}' so that TeX does not use a sentence space",
                           replacement=rep)


@register
class StrayApostrophe(Check):
    id = "stray-apostrophe"
    description = "An apostrophe after a space (« car ’elle »): probably a typo"
    category = "typography"
    severity = "warning"
    languages = frozenset(["fr"])

    def check(self, doc, ctx):
        for b in _prose_blocks(doc):
            for m in re.finditer(r"(?<=[\s\u00a0])[’'](?=[^\W\d_])", b.text):
                if b.is_verbatim(doc.source, m.start(), m.end()):
                    yield ctx.at_prose(self, doc, b, m.start(), m.end(), "stray apostrophe after a space: typo?")
