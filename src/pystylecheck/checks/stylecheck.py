"""The rule files and the built-in checks of style-check.rb."""

from __future__ import annotations

import re

from ..latex import BLOCK_SEP, MASK, Document
from ..latexdb import CITE_MACROS, PH_CITE, PH_CODE, PH_DISPLAY, PH_MATH, PH_OTHER, PH_REF, PH_UNIT
from . import Check, Context, register

_NUMERIC_CITES = "cite|citep|parencite|autocite|Cite|Parencite|Autocite|citenum|supercite|smartcite"


@register
class RuleFiles(Check):
    id = "rules"
    description = "Phrases, spellings, capitalizations and syntax from the rule files (style-check.rb format)"
    explanation = (
        "Each rule file line is a regular expression followed by '% kind explanation'. "
        "Kinds: syntax (source regex), capitalize (case-sensitive word), phrase (case-insensitive, "
        "spaces match any whitespace), spelling (case-insensitive word), prose (regex on the prose). "
        "Disable a whole kind with --disable phrase, or a whole file with --disable @passive-voice."
    )
    category = "rules"
    severity = "error"
    origin = "style-check"

    def check(self, doc: Document, ctx: Context):
        rs = ctx.rules
        if rs is None:
            return
        compat = ctx.opt("compat", False)
        sv = doc.source_view
        prose = doc.prose
        for rule in (rs.rules if compat else rs.for_language(doc.language)):
            kind_ids = {rule.kind, "@" + rule.file_stem}
            if ctx.opt("is_disabled")(kind_ids):
                continue
            sev = "warning" if rule.weak else "error"
            msg = rule.explanation or f"matched {rule.kind} rule '{rule.expression}'"
            if rule.weak and msg.endswith("?") and not msg.endswith("??"):
                msg = msg[:-1].rstrip()  # the final '?' only marks a weak rule
            elif msg.endswith("??"):
                msg = msg[:-1]
            seen_lines: set[int] = set()
            if rule.target == "source":
                for m in rule.regex.finditer(sv.text):
                    if m.end() == m.start() or m.group(0).count("\n") > 2:
                        continue
                    if sv.text[m.start()] == MASK:
                        continue
                    s, e = sv.src_span(m.start(), m.end())
                    f = ctx.make(self, doc, s, e, msg, severity=sev, check_id=rule.kind,
                                 explanation=rule.reason, category=rule.kind, rule_source=rule.source_ref,
                                 matched=m.group(0).replace(MASK, "").replace("\n", " "))
                    if compat:
                        if f.line in seen_lines:
                            continue
                        seen_lines.add(f.line)
                    f.tags.append("@" + rule.file_stem)
                    yield f
            else:
                for m in rule.regex.finditer(prose.text):
                    if m.end() == m.start() or BLOCK_SEP in m.group(0):
                        continue
                    bi = doc.block_of_prose(m.start())
                    if bi < 0:
                        continue
                    block = doc.blocks[bi]
                    base = doc._prose_block_starts[bi]
                    i, j = m.start() - base, m.end() - base
                    if j > len(block.text):
                        continue
                    f = ctx.at_prose(self, doc, block, i, j, msg, severity=sev, check_id=rule.kind,
                                     explanation=rule.reason, category=rule.kind, rule_source=rule.source_ref)
                    if compat:
                        if f.line in seen_lines:
                            continue
                        seen_lines.add(f.line)
                    f.tags.append("@" + rule.file_stem)
                    yield f


@register
class PercentAfterNumber(Check):
    id = "percent-after-number"
    description = "A comment sign right after a number is usually a forgotten \\%"
    explanation = "'50% of users' hides the rest of the line in a comment: write 50\\%."
    category = "latex"
    severity = "error"
    origin = "style-check"
    fixable = True

    def check(self, doc, ctx):
        src = doc.source
        for a, _ in doc.comment_spans:
            if a > 0 and src[a - 1].isdigit():
                yield ctx.make(self, doc, a - 1, a + 1, "a percent following a number is rarely an intended comment: write \\%",
                               replacement=src[a - 1] + "\\%")


_ABBREV_BEFORE_PERIOD = re.compile(r"(?:\bet al|\betc|\be\.g|\bi\.e|\bcf|\bvs|\bresp|\bal)$", re.I)


@register
class CiteAfterPeriod(Check):
    id = "cite-after-period"
    description = "A citation should precede the period"
    explanation = "Write 'as shown~\\cite{x}.' rather than 'as shown.~\\cite{x}'."
    category = "citation"
    severity = "error"
    origin = "style-check"
    fixable = True

    def check(self, doc, ctx):
        compat = ctx.opt("compat", False)
        sv = doc.source_view
        rx = re.compile(r"\.~?\\cite" if compat else r"\.(\s*)~?\\(?:%s)\b" % _NUMERIC_CITES)
        cites = {c.pos: c for c in doc.cites}
        for m in rx.finditer(sv.text):
            s, _ = sv.src_span(m.start(), m.end())
            if not compat and _ABBREV_BEFORE_PERIOD.search(doc.source[max(0, s - 6) : s]):
                continue
            cite_pos = sv.src(m.end() - 1)
            # find the cite macro that starts at the backslash
            bs = doc.source.rfind("\\", s, cite_pos + 1)
            c = cites.get(bs)
            if c is None or compat:
                yield ctx.make(self, doc, s, sv.src(m.end() - 1) + 1, "~\\cite{} should precede the period",
                               matched=m.group(0) if compat else None)
                continue
            cite_src = doc.source[c.pos : c.end]
            yield ctx.make(self, doc, s, c.end, "the citation should precede the period: text~\\cite{...}.",
                           replacement="~" + cite_src + ".")


@register
class CiteAsNoun(Check):
    id = "cite-as-noun"
    description = "A bracketed citation used as a noun ('in [3]')"
    explanation = (
        "Numbered citations are not nouns. Prefer 'Smith et al.~\\cite{x} show...' to 'in~\\cite{x}' "
        "or '[3] shows'."
    )
    category = "citation"
    severity = "error"
    origin = "style-check"

    WORDS = {"en": r"from|in|and|with|see|by", "fr": r"dans|selon|de|par|voir|avec|et"}

    def check(self, doc, ctx):
        compat = ctx.opt("compat", False)
        sv = doc.source_view
        words = self.WORDS["en"] if compat else self.WORDS.get(doc.language, self.WORDS["en"])
        cites = r"cite" if compat else r"(?:%s)\b" % _NUMERIC_CITES
        rx = re.compile(r"\b(%s)[~ ]+\\%s" % (words, cites), 0 if compat else re.I)
        for m in rx.finditer(sv.text):
            s, e = sv.src_span(m.start(), m.end())
            yield ctx.make(self, doc, s, e, "don't cite in the sentence as 'in [x]', cites are not nouns. "
                           "Prefer: Smith et al.~\\cite{...} show ...")
        if compat:
            return
        # a sentence that starts with a numbered citation: "[3] shows that"
        from ..text import split_sentences

        for b in doc.prose_blocks("paragraph", "item", "footnote", "caption"):
            for sent in split_sentences(b.text, doc.language):
                if not re.match(PH_CITE + r"[\s\u00a0]+[^\W\d_]", b.text[sent.start : sent.end]):
                    continue
                if sent.start == 0 and b.start_reason not in ("blank", "heading", "start", "env-begin"):
                    continue
                i = sent.start
                s, e = b.span(i, i + 1)
                if re.match(r"\\(%s)\b" % _NUMERIC_CITES, doc.source[s:e]):
                    yield ctx.at_prose(self, doc, b, i, i + 1,
                                       "a sentence should not start with a numbered citation: name the authors",
                                       severity="warning")


_SENTENCE_END = re.compile(r"[.!?:…;]|\\@|\.\)")


@register
class ParagraphEnd(Check):
    id = "paragraph-end"
    description = "Paragraphs should end with the end of a sentence"
    explanation = (
        "A paragraph that does not end with '.', '!', '?' or ':' often means a sentence was cut "
        "or a stray blank line split a paragraph."
    )
    category = "structure"
    severity = "warning"
    origin = "style-check"

    def check(self, doc, ctx):
        if ctx.opt("compat", False):
            sv = doc.source_view.text
            for m in re.finditer(r"[a-z0-9][^\.\:\!\?\n}]\n\n", sv):
                s, e = doc.source_view.src_span(m.start(), m.end() - 2)
                yield ctx.make(self, doc, s, e, "apparent bad paragraph break")
            return
        for b in doc.prose_blocks("paragraph"):
            if b.end_reason not in ("blank", "heading", "eof", "env-end"):
                continue
            text = b.text.rstrip()
            if not b.has_words or not text:
                continue
            # strip closing quotes, parentheses and braces
            t = re.sub(r"[\s”»\"’')\]}\u00a0]+$", "", text)
            # "fast.~\cite{x}": the sentence did end (cite-after-period reports the order)
            t2 = re.sub("[\\s\u00a0" + PH_CITE + PH_REF + "]+$", "", t)
            if t2 != t and t2 and t2[-1] in ".!?":
                continue
            if not t:
                continue
            last = t[-1]
            if last in ".!?:…;," or last in (PH_DISPLAY, PH_OTHER, PH_CODE, PH_UNIT):
                continue
            if last in (PH_MATH,):
                # an inline formula may hold the period: $x.$
                s, e = b.span(len(t) - 1, len(t))
                if re.search(r"[.!?]\s*\$?\s*$", doc.source[s:e - 1] if e - s > 1 else ""):
                    continue
            # a paragraph made of one command (\ccsdesc{...}, \received{...}) is metadata
            src_par = doc.source[b.starts[0] : b.end].strip() if b.starts else ""
            lead = len(b.text) - len(b.text.lstrip())
            first_src = doc.source[b.starts[lead]] if lead < len(b.starts) else ""
            if first_src == "\\" and not b.is_verbatim(doc.source, lead, lead + 1) and src_par.rstrip().endswith("}") and src_par.count("\n") < 3:
                continue
            # short lines without verbs (e.g. "Keywords: ...", signatures) are noise
            words = re.findall(r"[^\W\d_]+", t)
            if len(words) < 4:
                continue
            i = len(t) - 1
            yield ctx.at_prose(self, doc, b, i, i + 1, "paragraph should end with a sentence end (missing period?)")


_REF_MACROS = r"ref|eqref|pageref|autoref|cref|Cref|vref|nameref|subref"
_REF_NAMES = (
    r"Tables?|Figures?|Fig\.|Figs\.|Sections?|Sec\.|Secs\.|Chapters?|Chap\.|Appendix|Appendices|Equations?|Eqs?\.|"
    r"Algorithms?|Alg\.|Theorems?|Thm\.|Lemmas?|Lemmata|Corollary|Corollaries|Definitions?|Def\.|Propositions?|"
    r"Listings?|Lines?|Steps?|Parts?|Examples?|Remarks?|Proofs?|Claims?|Conjectures?|Exercises?|Tableaux|Tableau|"
    r"Chapitres?|Annexes?|Équations?|Éq\.|Algorithmes?|Théorèmes?|Lemmes?|Corollaires?|Définitions?|Exemples?|"
    r"Pages?|pp?\.|Problems?|Problèmes?|Hypothesis|Hypothèses?|Cases?|Cas|Items?|Notes?|Footnotes?|Rows?|Columns?|Lignes?|Colonnes?"
)


@register
class RefNonBreakingSpace(Check):
    id = "ref-nbsp"
    description = "Figure, Table, Section... before \\ref need a non-breaking space"
    explanation = "Write Figure~\\ref{fig:x} so that 'Figure' and its number never end up on different lines."
    category = "reference"
    severity = "error"
    origin = "style-check"
    fixable = True

    def check(self, doc, ctx):
        sv = doc.source_view
        if ctx.opt("compat", False):
            rx = re.compile(r"(Table|Figure|Section)[ \n]\\ref")
        else:
            rx = re.compile(r"(?<![\w\\])(%s)([ \t]*\n?[ \t]*)\\(?:%s)\b" % (_REF_NAMES, _REF_MACROS), re.I)
        for m in rx.finditer(sv.text):
            if not ctx.opt("compat", False) and not m.group(2):
                continue
            s, e = sv.src_span(m.start(), m.end())
            if ctx.opt("compat", False):
                yield ctx.make(self, doc, s, e, "Table, Figure, and Section refs should have a non-breaking space")
                continue
            ws_s, ws_e = sv.src_span(m.start(2), m.end(2))
            if "%" in doc.source[ws_s:ws_e]:
                continue
            yield ctx.make(self, doc, s, e, f"use a non-breaking space: {m.group(1)}~\\ref{{...}}",
                           replacement=doc.source[s:ws_s] + "~" + doc.source[ws_e:e])


@register
class RefCapitalization(Check):
    id = "ref-capitalization"
    description = "Capitalize Table, Figure, Section... when they name a numbered element (English)"
    explanation = "In English, 'Figure~3' and 'Section~2' are proper names and take a capital."
    category = "reference"
    severity = "error"
    languages = frozenset(["en"])
    origin = "style-check"
    fixable = True

    def check(self, doc, ctx):
        sv = doc.source_view
        if ctx.opt("compat", False):
            rx = re.compile(r"(table|figure|section)~\\ref")
        else:
            rx = re.compile(r"(?<![\w\\-])(tables?|figures?|sections?|chapters?|appendix|appendices|algorithms?|listings?|theorems?|lemmas?|corollary|definitions?)(?:~|[ \t]*\n?[ \t]*)\\(?:%s)\b" % _REF_MACROS)
        for m in rx.finditer(sv.text):
            s, e = sv.src_span(m.start(), m.end())
            word = m.group(1)
            ws, we = sv.src_span(m.start(1), m.end(1))
            yield ctx.make(self, doc, ws, we, "Table, Figure, and Section refs should be capitalized",
                           replacement=word[0].upper() + word[1:])


@register
class UrlScheme(Check):
    id = "url-scheme"
    description = "\\url{} should start with http://, https://, ftp:// or mailto:"
    category = "latex"
    severity = "error"
    origin = "style-check"

    def check(self, doc, ctx):
        for m in re.finditer(r"\\url\s*\{(?!https?:|ftp|rtsp|mailto|file:|\s*\})", doc.source):
            if doc.in_comment(m.start()) or doc.in_code(m.start()) and not doc.in_code(m.end()):
                continue
            yield ctx.make(self, doc, m.start(), m.end(), "\\url{} should start with http:// (or ftp or rtsp or maybe mailto)")
