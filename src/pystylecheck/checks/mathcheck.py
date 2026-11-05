"""Checks on mathematical typography."""

from __future__ import annotations

import re

from ..latexdb import PH_DISPLAY
from . import Check, register

_FUNCTIONS = (
    "sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|sinh|cosh|tanh|coth|log|ln|lg|exp|max|min|sup|inf|"
    "lim|liminf|limsup|det|dim|ker|gcd|deg|arg|Pr|hom|argmax|argmin|mod|tr|rank|sgn"
)
_TEXT_IN_MATH = re.compile(r"\\(?:text\w*|mathrm|operatorname\*?|mathit|mathsf|mathtt|mbox|label|tag|mathbf|mathcal|mathbb|mathfrak|begin|end|ref|eqref|hbox|intertext|SI|si|unit|qty|num)\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}")


def _math_bodies(doc):
    for m in doc.maths:
        body = doc.source[m.body_start : m.body_end]
        # blank out text-like arguments and command names
        masked = _TEXT_IN_MATH.sub(lambda x: " " * len(x.group(0)), body)
        masked = re.sub(r"\\[A-Za-z]+", lambda x: " " * len(x.group(0)), masked)
        masked = re.sub(r"%[^\n]*", lambda x: " " * len(x.group(0)), masked)
        yield m, body, masked


@register
class MathFunctionNames(Check):
    id = "math-function-names"
    description = "Write \\sin, \\log, \\max... in math, not sin, log, max"
    explanation = (
        "Function names such as sin, log and cos are upright, not italic: $\\sin(x)$, not $sin(x)$. "
        "Use \\operatorname{} for names LaTeX does not know."
    )
    category = "math"
    severity = "warning"
    origin = "guide"
    fixable = True

    def check(self, doc, ctx):
        rx = re.compile(r"(?<![A-Za-z])(%s)(?![A-Za-z])" % _FUNCTIONS)
        for m, body, masked in _math_bodies(doc):
            for f in rx.finditer(masked):
                s = m.body_start + f.start(1)
                name = f.group(1)
                rep = "\\" + name if name not in ("argmax", "argmin", "sgn", "tr", "rank") else "\\operatorname{%s}" % name
                yield ctx.make(self, doc, s, s + len(name), f"use {rep} so that '{name}' is set upright", replacement=rep)


@register
class MathWordSubscript(Check):
    id = "math-word-subscript"
    description = "Words in subscripts and superscripts should be upright: x_{\\mathrm{max}}"
    explanation = (
        "Variables are single italic letters; a word in a formula is not italic: write "
        "$x_{\\mathrm{temps}}$, not $x_{temps}$."
    )
    category = "math"
    severity = "warning"
    origin = "guide"
    fixable = True

    def check(self, doc, ctx):
        rx = re.compile(r"[_^]\s*\{\s*([A-Za-zÀ-ÿ]{3,})\s*\}")
        for m, body, masked in _math_bodies(doc):
            for f in rx.finditer(masked):
                word = body[f.start(1) : f.end(1)]
                if word != masked[f.start(1) : f.end(1)]:
                    continue
                s = m.body_start + f.start(1)
                yield ctx.make(self, doc, s, s + len(word), f"'{word}' is a word: write \\mathrm{{{word}}} (or \\text{{{word}}})",
                               replacement="\\mathrm{%s}" % word)


@register
class DisplayMathPunctuation(Check):
    id = "display-math-punctuation"
    description = "A displayed formula is part of a sentence: end it with a period or a comma"
    explanation = (
        "A formula belongs to a sentence even when displayed on its own line. When the sentence ends "
        "with the formula, the formula ends with a period; when it continues ('where c is a "
        "constant'), it ends with a comma."
    )
    category = "math"
    severity = "warning"
    origin = "guide"

    _CONTINUATIONS = {"where", "with", "for", "and", "or", "if", "when", "which", "so", "où", "avec", "pour", "et", "ou", "si", "lorsque", "quand", "donc"}

    def check(self, doc, ctx):
        displays = {m.pos: m for m in doc.maths if m.display}
        for b in doc.prose_blocks("paragraph", "item", "footnote"):
            for i, c in enumerate(b.text):
                if c != PH_DISPLAY:
                    continue
                s, e = b.span(i, i + 1)
                m = displays.get(s)
                if m is None:
                    continue
                body = doc.source[m.body_start : m.body_end]
                body = re.sub(r"%[^\n]*", "", body)
                body = re.sub(r"\\(?:label|tag)\*?\{[^}]*\}|\\(?:nonumber|notag)\b", "", body)
                body = re.sub(r"(\\\\|\\[,;:!]|\\q?quad|\\[a-z]*space|\\hfill|\s|~)+$", "", body)
                body = re.sub(r"(\\right[.)\]|]?|\\end\{\w+\*?\})+$", "", body).rstrip()
                if not body or body[-1] in ".,;:!?" or re.search(r"\\text\{\s*[.,;]\s*\}$|[.,;]\s*\}*$", body):
                    continue
                after = b.text[i + 1 :]
                am = re.match(r"[\s\u00a0]*([.,;:])", after)
                if am:
                    continue  # punctuation right after the environment
                wm = re.match(r"[\s\u00a0]*([^\W\d_]+)", after)
                if not wm:
                    if not after.strip():
                        yield ctx.make(self, doc, m.body_end - 1, m.body_end, "the formula ends the sentence: end it with a period")
                    continue
                w = wm.group(1)
                if w[0].isupper():
                    yield ctx.make(self, doc, m.body_end - 1, m.body_end, "the formula ends the sentence: end it with a period")
                elif w.lower() in ("where", "où"):
                    yield ctx.make(self, doc, m.body_end - 1, m.body_end, f"the sentence continues with '{w}': end the formula with a comma")


@register
class DoubleDollar(Check):
    id = "double-dollar"
    description = "Use \\[ ... \\] rather than $$ ... $$"
    explanation = "$$ is plain TeX: it breaks vertical spacing and fleqn. Use \\[ ... \\] or an equation environment."
    category = "math"
    severity = "warning"
    fixable = True

    def check(self, doc, ctx):
        for m in doc.maths:
            if doc.source.startswith("$$", m.pos) and m.display:
                yield ctx.make(self, doc, m.pos, m.end, "use \\[ ... \\] rather than $$ ... $$",
                               replacement="\\[" + doc.source[m.pos + 2 : m.end - 2] + "\\]")
