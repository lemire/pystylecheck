"""Checks on document structure: headings, sections and paragraphs."""

from __future__ import annotations

import re

from ..latexdb import PH_DISPLAY, PH_MATH, PLACEHOLDERS
from ..text import split_sentences
from . import Check, register

_FOLLOWER_NAMES = {
    "list": "a list",
    "code": "a code block or picture",
    "tabular": "a table",
}


def _heading_label(h) -> str:
    title = re.sub(r"\s+", " ", "".join(c for c in h.block.text if c not in PLACEHOLDERS)).strip()
    return f"\\{h.macro}{{{title}}}" if title else f"\\{h.macro}"


@register
class HeadingWithoutParagraph(Check):
    id = "heading-without-paragraph"
    description = "A heading must be followed by text, not by another heading, a list or an equation"
    explanation = (
        "A section title should always be followed immediately by a few lines of text. A chapter or "
        "section does not start with a subsection, a list, a table or a formula: introduce it with "
        "a paragraph first. Floats (figures, tables) are ignored since they move."
    )
    category = "structure"
    severity = "error"
    origin = "guide"

    def check(self, doc, ctx):
        events = doc.events
        for k, ev in enumerate(events):
            if ev.kind != "heading":
                continue
            h = ev.obj
            for nxt in events[k + 1 :]:
                if nxt.kind in ("float",):
                    continue
                if nxt.kind == "include":
                    break  # the text is in another file
                if nxt.kind == "paragraph":
                    b = nxt.obj
                    t = b.text.strip(" \t\n ")
                    if b.has_words:
                        if t and t[0] == PH_DISPLAY:
                            yield ctx.make(self, doc, h.pos, h.end, f"{_heading_label(h)} is followed by a formula: start with a sentence")
                        break
                    if PH_DISPLAY in t or PH_MATH in t:
                        yield ctx.make(self, doc, h.pos, h.end, f"{_heading_label(h)} is followed by a formula: start with a sentence")
                    break  # unknown content (a macro): give it the benefit of the doubt
                if nxt.kind == "heading":
                    h2 = nxt.obj
                    if h2.level > h.level:
                        msg = f"{_heading_label(h)} starts directly with {_heading_label(h2)}: add an introductory paragraph"
                    else:
                        msg = f"{_heading_label(h)} has no text: it is directly followed by {_heading_label(h2)}"
                    yield ctx.make(self, doc, h.pos, h.end, msg)
                    break
                if nxt.kind in _FOLLOWER_NAMES:
                    yield ctx.make(self, doc, h.pos, h.end,
                                   f"{_heading_label(h)} is followed by {_FOLLOWER_NAMES[nxt.kind]}: start with a paragraph",
                                   severity="warning")
                    break
                if nxt.kind == "eof":
                    yield ctx.make(self, doc, h.pos, h.end, f"{_heading_label(h)} is not followed by any text")
                    break


@register
class ShortSection(Check):
    id = "short-section"
    description = "A section or subsection with a single paragraph"
    explanation = (
        "Sections, including subsections, usually have at least three paragraphs. Avoid sections "
        "with a single paragraph: merge them with a neighbour or develop them."
    )
    category = "structure"
    severity = "info"
    origin = "guide"

    def check(self, doc, ctx):
        events = doc.events
        for k, ev in enumerate(events):
            if ev.kind != "heading" or not (0 <= ev.obj.level <= 3):
                continue
            h = ev.obj
            paragraphs = 0
            sub = False
            complete = False
            for nxt in events[k + 1 :]:
                if nxt.kind == "heading":
                    if nxt.obj.level > h.level:
                        sub = True
                    complete = True
                    break
                if nxt.kind == "paragraph" and nxt.obj.has_words and nxt.obj.kind == "paragraph":
                    if nxt.obj.start_reason != "continuation":
                        paragraphs += 1
                if nxt.kind == "include":
                    break
                if nxt.kind == "eof":
                    complete = True
            if complete and not sub and paragraphs == 1:
                yield ctx.make(self, doc, h.pos, h.end, f"{_heading_label(h)} has a single paragraph")


@register
class SingleSentenceParagraph(Check):
    id = "single-sentence-paragraph"
    description = "A paragraph made of a single sentence"
    explanation = (
        "Paragraphs generally have more than one sentence, most often at least three. Avoid "
        "one-sentence paragraphs."
    )
    category = "structure"
    severity = "info"
    origin = "guide"

    def check(self, doc, ctx):
        for b in doc.prose_blocks("paragraph"):
            if b.start_reason not in ("blank", "heading", "start", "env-begin"):
                continue
            if b.end_reason not in ("blank", "heading", "eof", "env-end"):
                continue
            if b.env not in (None, "document", "abstract"):
                continue
            t = b.text.strip()
            if not b.has_words or t.endswith(":") or len(re.findall(r"[^\W\d_]+", t)) < 4:
                continue
            if len(split_sentences(b.text, doc.language)) == 1:
                i = len(b.text) - len(b.text.lstrip())
                yield ctx.at_prose(self, doc, b, i, i + 1, "paragraph with a single sentence")


_ACRONYM = re.compile(r"(?<![\w-])([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ0-9]*[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ0-9]*)(?:s)?(?![\w])")
_ROMAN = re.compile(r"^[IVXLCDM]+$")


@register
class AcronymInHeading(Check):
    id = "acronym-in-heading"
    description = "Acronyms in titles and headings"
    explanation = "Do not use acronyms in titles: spell them out (guide, Qualité de la langue)."
    category = "structure"
    severity = "warning"
    languages = frozenset(["fr"])
    origin = "guide"

    def check(self, doc, ctx):
        allowed = set(ctx.opt("acronyms_allowed", []))
        for b in doc.prose_blocks("heading", "title"):
            letters = [c for c in b.text if c.isalpha()]
            if letters and all(c.isupper() for c in letters):
                continue  # an all-caps title is a style, not acronyms
            for m in _ACRONYM.finditer(b.text):
                w = m.group(1)
                if _ROMAN.match(w) or w in allowed or not b.is_verbatim(doc.source, m.start(1), m.end(1)):
                    continue
                yield ctx.at_prose(self, doc, b, m.start(1), m.end(1), f"avoid acronyms in titles: spell out '{w}'")


@register
class HeadingPunctuation(Check):
    id = "heading-period"
    description = "Headings do not end with a period"
    category = "structure"
    severity = "warning"

    def check(self, doc, ctx):
        for b in doc.prose_blocks("heading"):
            if b.level is not None and b.level >= 4:
                continue  # \paragraph{Run-in heading.} conventionally ends with a period
            t = b.text.rstrip()
            if t.endswith(".") and not t.endswith("..") and not re.search(r"\b(?:etc|al|cf)\.$", t):
                yield ctx.at_prose(self, doc, b, len(t) - 1, len(t), "a heading should not end with a period")
