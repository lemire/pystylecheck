"""Checks on citations, cross-references and labels."""

from __future__ import annotations

import re
from collections import defaultdict

from ..latexdb import FLOAT_ENVS
from . import Check, ProjectCheck, register

_NUMERIC_CITES = r"cite|citep|parencite|autocite|citenum|Cite|Parencite|Autocite|supercite"


@register
class CiteNonBreakingSpace(Check):
    id = "cite-nbsp"
    description = "Use a non-breaking space before \\cite"
    explanation = (
        "A citation must not start a line: write 'Smith et al.~\\cite{x}'. In French, the opening "
        "bracket of a numbered citation is preceded by a non-breaking space."
    )
    category = "citation"
    severity = "warning"
    origin = "guide"
    fixable = True

    def check(self, doc, ctx):
        sv = doc.source_view
        rx = re.compile(r"([^\s(\[{~])([ \t]+\n?[ \t]*|\n[ \t]*)\\(?:%s)\b" % _NUMERIC_CITES)
        for m in rx.finditer(sv.text):
            ws, we = sv.src_span(m.start(2), m.end(2))
            if "%" in doc.source[ws:we]:
                continue
            yield ctx.make(self, doc, ws, we + 1, "use a non-breaking space before the citation: ~\\cite{...}",
                           replacement="~\\", matched=doc.source[ws:we + 1])


@register
class ConsecutiveCites(Check):
    id = "consecutive-cites"
    description = "Merge consecutive citations: \\cite{a,b} rather than \\cite{a}\\cite{b}"
    explanation = "With several references, join them: [1][2] becomes [1,2]."
    category = "citation"
    severity = "warning"
    origin = "guide"
    fixable = True

    def check(self, doc, ctx):
        cites = sorted(doc.cites, key=lambda c: c.pos)
        src = doc.source
        k = 0
        while k + 1 < len(cites):
            a = cites[k]
            run = [a]
            j = k + 1
            while j < len(cites) and cites[j].macro == a.macro and re.fullmatch(r"[\s~,;]*", src[run[-1].end : cites[j].pos]):
                run.append(cites[j])
                j += 1
            if len(run) > 1:
                plain = all(re.fullmatch(r"\\%s\s*\{[^{}]*\}" % re.escape(c.macro), src[c.pos : c.end]) for c in run)
                rep = None
                if plain:
                    keys = [key for c in run for key in c.keys]
                    rep = "\\%s{%s}" % (a.macro, ",".join(keys))
                yield ctx.make(self, doc, a.pos, run[-1].end,
                               f"merge consecutive citations into one \\{a.macro}{{...}}", replacement=rep)
            k = j


_HARDCODED = re.compile(
    r"(?<![\w\\])(Figures?|Figs?\.|Tables?|Tableaux?|Sections?|Secs?\.|Chapters?|Chapitres?|Chap\.|"
    r"Equations?|Équations?|Eqs?\.|Éq\.|Algorithms?|Algorithmes?|Appendix|Annexes?|Theorems?|Théorèmes?|"
    r"Lemmas?|Lemmes?|§)[\s\u00a0]*\(?(\d+(?:\.\d+)*)\b",
    re.I,
)


@register
class HardcodedReference(Check):
    id = "hardcoded-reference"
    description = "Numbers typed by hand instead of \\ref ('Figure 3')"
    explanation = (
        "Never type figure, table, section or equation numbers by hand: they go stale when the "
        "document changes. Use \\label and \\ref."
    )
    category = "reference"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        for b in doc.prose_blocks("paragraph", "item", "footnote", "caption"):
            for m in _HARDCODED.finditer(b.text):
                if not b.is_verbatim(doc.source, m.start(2), m.end(2)):
                    continue
                yield ctx.at_prose(self, doc, b, m.start(), m.end(),
                                   f"'{m.group(0).strip()}' is typed by hand: use \\ref{{...}}")


@register
class SubsectionReference(Check):
    id = "subsection-reference"
    description = "Refer to subsections as sections ('Section~3.4' or '§~3.4')"
    explanation = "Avoid writing 'see subsection 5.2': write 'see Section 5.2' or '§ 5.2'."
    category = "reference"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        sv = doc.source_view
        rx = re.compile(r"(?<![\w-])((?:sub)+sections?|sous-sections?)(?:~|[ \t]*\n?[ \t]*)(\\(?:ref|cref|autoref)\b|\d)", re.I)
        for m in rx.finditer(sv.text):
            s, e = sv.src_span(m.start(1), m.end(1))
            word = "section" if doc.language == "fr" else "Section"
            yield ctx.make(self, doc, s, e, f"avoid '{m.group(1)}': write '{word}~\\ref{{...}}' or '\\S~\\ref{{...}}'")


def _float_kind(env: str) -> str:
    if "table" in env:
        return "table"
    if "algorithm" in env:
        return "algorithm"
    if "listing" in env:
        return "listing"
    return "figure"


@register
class UnreferencedFloat(ProjectCheck):
    id = "unreferenced-float"
    description = "Every figure and table needs a caption, a \\label and a reference in the text"
    explanation = (
        "All figures and tables are numbered and must be referenced in the main text. A float "
        "without \\caption has no number; without \\label it cannot be referenced. Only checked when "
        "the main file (with \\begin{document}) is part of the run."
    )
    category = "float"
    severity = "warning"
    origin = "guide"

    def check_project(self, docs, ctx):
        if not any(d.is_root for d in docs):
            return
        referenced = {k for d in docs for r in d.refs for k in r.keys}
        for d in docs:
            for f in d.floats:
                if f.env in ("subfigure", "subtable"):
                    continue
                kind = _float_kind(f.env)
                if not f.captions:
                    yield ctx.make(self, d, f.pos, f.pos + len(f.env) + 8, f"{kind} without \\caption: it has no number and cannot be referenced")
                    continue
                if not f.labels:
                    yield ctx.make(self, d, f.pos, f.pos + len(f.env) + 8, f"{kind} without \\label: it cannot be referenced in the text")
                    continue
                if not any(k in referenced for k, _, _ in f.labels):
                    key, p, e = f.labels[0]
                    yield ctx.make(self, d, p, e, f"{kind} '{key}' is never referenced in the text")


_FAMILIES = {
    "figure": "figure",
    "fig": "figure",
    "figs": "figure",
    "figures": "figure",
    "table": "table",
    "tables": "table",
    "tab": "table",
    "tableau": "table",
    "tableaux": "table",
    "equation": "equation",
    "equations": "equation",
    "équation": "equation",
    "équations": "equation",
    "eq": "equation",
    "eqs": "equation",
    "eqn": "equation",
    "éq": "equation",
    "section": "section",
    "sections": "section",
    "sec": "section",
    "secs": "section",
    "§": "section",
    "chapter": "chapter",
    "chapters": "chapter",
    "chapitre": "chapter",
    "chapitres": "chapter",
    "chap": "chapter",
    "ch": "chapter",
}


@register
class ReferenceStyle(ProjectCheck):
    id = "reference-style"
    description = "Refer to figures (tables, sections...) consistently: 'Fig.' or 'Figure', not both"
    explanation = (
        "References to figures must be consistent (Fig. 1, figure 1, Figure 1: choose one). The form "
        "used most often wins; the others are reported."
    )
    category = "reference"
    severity = "warning"
    origin = "guide"

    def check_project(self, docs, ctx):
        uses: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        rx = re.compile(r"(§|[A-Za-zÀ-ÿ]+\.?)[\s~\u00a0]*$")
        for d in docs:
            for r in d.refs:
                if r.macro not in ("ref", "pageref", "eqref", "vref"):
                    continue
                before = d.source[max(0, r.pos - 30) : r.pos]
                m = rx.search(before)
                if not m:
                    continue
                word = m.group(1)
                fam = _FAMILIES.get(word.lower().rstrip("."))
                if fam is None:
                    continue
                form = "abbreviated" if word.endswith(".") or word == "§" else "full"
                uses[fam][form].append((d, r.pos - len(before) + m.start(1), word))
        for fam, forms in uses.items():
            if len(forms) < 2:
                continue
            ranked = sorted(forms.items(), key=lambda kv: -len(kv[1]))
            main_form, main_uses = ranked[0]
            example = main_uses[0][2]
            for form, lst in ranked[1:]:
                for d, pos, word in lst:
                    yield ctx.make(self, d, pos, pos + len(word),
                                   f"inconsistent reference style: '{word}' here, but '{example}' {len(main_uses)} time(s) elsewhere")
