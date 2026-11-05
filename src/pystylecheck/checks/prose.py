"""Checks on the prose itself: repeated words, sentences, spacing."""

from __future__ import annotations

import re

from ..latexdb import PH_DISPLAY, PH_MATH, PLACEHOLDERS
from ..text import first_token, split_sentences, word_count
from . import Check, register

# Repetitions that are often correct ("that that", "nous nous demandons").
DUPLICATE_ALLOWED = {
    "en": {"that", "had", "do", "bye", "ha", "no", "so"},
    "fr": {"nous", "vous", "que", "si"},
}

PROSE_KINDS = ("paragraph", "item", "footnote", "caption", "heading", "title", "cell")
SENTENCE_KINDS = ("paragraph", "footnote", "caption")


@register
class DuplicateWord(Check):
    id = "duplicate-word"
    description = "The same word twice in a row ('the the')"
    explanation = (
        "Repeated words survive proofreading because the eye skips them, especially across a line "
        "break or markup (\\emph{the} the). Allowed repetitions (e.g. 'that that', 'nous nous') can "
        "be configured with duplicate_allowed."
    )
    category = "prose"
    severity = "error"
    fixable = True

    def check(self, doc, ctx):
        allowed = set(DUPLICATE_ALLOWED.get(doc.language, set()))
        allowed |= {w.lower() for w in ctx.opt("duplicate_allowed", [])}
        rx = re.compile(r"(?<![\w'’-])([^\W\d_][\w'’-]*)([\s ]+)(\1)(?![\w'’-])", re.I)
        for b in doc.prose_blocks(*PROSE_KINDS):
            for m in rx.finditer(b.text):
                w = m.group(1)
                if w[1:] != m.group(3)[1:]:
                    continue  # "and AND/OR": different words
                if w.lower() in allowed or (len(w) == 1 and not w.isalpha()):
                    continue
                # "A a" across a sentence start is fine only with punctuation, which the regex excludes
                rep = None
                if b.is_verbatim(doc.source, m.end(1), m.end(3)):
                    rep = ""
                s, _ = b.span(m.end(1), m.end(1) + 1)
                _, e = b.span(m.end(3) - 1, m.end(3))
                if rep is None:
                    yield ctx.at_prose(self, doc, b, m.start(1), m.end(3), f"repeated word: '{w} {m.group(3)}'")
                else:
                    f = ctx.make(self, doc, s, e, f"repeated word: '{w} {m.group(3)}'", replacement="")
                    # report from the first word for readability, fix only removes the second
                    fs, _ = b.span(m.start(1), m.start(1) + 1)
                    f.line, f.column = doc.line_col(fs)
                    f.excerpt = doc.line_text(f.line)
                    f.matched = doc.source[fs:e]
                    yield f


_LOWER_OK = re.compile(r"^(?:e\.g|i\.e|etc|cf|vs|et|p|pp|x86|iOS|eBay|iPhone|iPad|macOS|npm|pip|uv|git|arXiv)$")


@register
class SentenceCapital(Check):
    id = "sentence-capital"
    description = "A sentence should start with a capital letter"
    explanation = (
        "After a period, the next sentence starts with a capital letter. A lowercase word after a "
        "period often reveals a missing abbreviation escape or a sentence that was cut."
    )
    category = "prose"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        for b in doc.prose_blocks(*SENTENCE_KINDS, "item"):
            sentences = split_sentences(b.text, doc.language)
            for k, s in enumerate(sentences):
                if k == 0 and (b.start_reason not in ("blank", "heading", "start", "env-begin", "") or b.kind in ("footnote", "item")):
                    continue
                if k > 0:
                    prev = b.text[sentences[k - 1].start : sentences[k - 1].end].rstrip()
                    if prev.endswith("…") or prev.endswith("..."):
                        continue
                tok = first_token(b.text[s.start : s.end])
                if tok is None:
                    continue
                i, w = tok
                if w[0] in PLACEHOLDERS or not w[0].isalpha():
                    continue
                if w[0].islower() and not any(c.isupper() for c in w) and not _LOWER_OK.match(w):
                    a = s.start + i
                    yield ctx.at_prose(self, doc, b, a, a + len(w), f"sentence should start with a capital letter: '{w}'")


@register
class MathStartsSentence(Check):
    id = "math-starts-sentence"
    description = "A sentence should not start with a formula"
    explanation = (
        "A mathematical expression never starts a sentence (guide, Typographie mathématique): write "
        "'The variable $x$ is...' rather than '$x$ is...'."
    )
    category = "math"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        for b in doc.prose_blocks(*SENTENCE_KINDS):
            sentences = split_sentences(b.text, doc.language)
            for k, s in enumerate(sentences):
                if k == 0 and b.start_reason not in ("blank", "heading", "start", "env-begin"):
                    continue
                tok = first_token(b.text[s.start : s.end])
                if tok and tok[1] in (PH_MATH,):
                    a = s.start + tok[0]
                    yield ctx.at_prose(self, doc, b, a, a + 1, "a sentence should not start with a formula")


@register
class LongSentence(Check):
    id = "long-sentence"
    description = "Very long sentences (more than max_sentence_words words, default 30)"
    explanation = (
        "Prefer short sentences: the guide recommends fewer than 15 words. Long sentences hide "
        "unclear ideas. The threshold is the max_sentence_words option."
    )
    category = "prose"
    severity = "info"
    origin = "guide"

    def check(self, doc, ctx):
        limit = int(ctx.opt("max_sentence_words", 30))
        for b in doc.prose_blocks(*SENTENCE_KINDS):
            for s in split_sentences(b.text, doc.language):
                n = word_count(b.text[s.start : s.end])
                if n > limit:
                    yield ctx.at_prose(self, doc, b, s.start, s.start + 1,
                                       f"long sentence ({n} words, more than {limit}): consider splitting it")


@register
class SpaceBeforePunctuation(Check):
    id = "space-before-punctuation"
    description = "No space before a comma or a period"
    explanation = "There is never a space before a period or a comma, in English or in French."
    category = "typography"
    severity = "error"
    origin = "guide"
    fixable = True

    def check(self, doc, ctx):
        # French puts a (thin) space before ! and ?: only check those in English
        marks = ",.!?" if doc.language == "en" else ",."
        rx = re.compile(r"(\S)([ \t\n\u00a0]+)([%s])(?![.\d])" % re.escape(marks))
        for b in doc.prose_blocks(*PROSE_KINDS):
            for m in rx.finditer(b.text):
                if m.group(1) in ".,!?":
                    continue
                if m.group(3) == "." and re.match(r"[^\W\d_]", b.text[m.end() : m.end() + 1]):
                    continue  # ".NET", ".tex files"
                if not b.is_verbatim(doc.source, m.start(2), m.end(3)):
                    # the space might come from removed markup (\label{x} ,)
                    s, e = b.span(m.start(2), m.end(3))
                    gap = doc.source[s:e]
                    if not re.fullmatch(r"[ \t\n~]+[,.]", gap):
                        continue
                s, e = b.span(m.start(2), m.end(3))
                yield ctx.make(self, doc, s, e, f"no space before '{m.group(3)}'", replacement=m.group(3))


@register
class ParenthesisSpacing(Check):
    id = "parenthesis-spacing"
    description = "Put a space before '(' and after ')' in running text"
    explanation = (
        "Within a sentence, an opening parenthesis is preceded by a space and a closing parenthesis "
        "is followed by a space or punctuation: 'Up (SNAFU) is', not 'Up(SNAFU)is'."
    )
    category = "typography"
    severity = "warning"
    origin = "guide"
    fixable = True

    _plural = re.compile(r"\((?:s|es|e|x|ne|nes|le|les|te|tes|euse|euses|rice|rices|ère|ères|ive|ives|ale|ales)\)", re.I)

    def check(self, doc, ctx):
        for b in doc.prose_blocks("paragraph", "item", "footnote", "caption"):
            t = b.text
            for m in re.finditer(r"([^\W\d_])\(", t):
                if self._plural.match(t, m.end() - 1):
                    continue
                if not b.is_verbatim(doc.source, m.start(), m.end()):
                    continue
                s, e = b.span(m.start(), m.end())
                yield ctx.make(self, doc, s, e, "put a space before an opening parenthesis",
                               replacement=m.group(1) + " (")
            for m in re.finditer(r"\)([^\W\d_])", t):
                k = t.rfind("(", 0, m.start())
                if k >= 0 and self._plural.match(t, k):
                    continue
                if not b.is_verbatim(doc.source, m.start(), m.end()):
                    continue
                s, e = b.span(m.start(), m.end())
                yield ctx.make(self, doc, s, e, "put a space after a closing parenthesis",
                               replacement=") " + m.group(1))
