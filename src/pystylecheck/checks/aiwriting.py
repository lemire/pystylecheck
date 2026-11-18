"""Patterns typical of AI-generated prose, from avoid-ai-writing.

The patterns come from Conor Bronsdon's avoid-ai-writing
(https://github.com/conorbronsdon/avoid-ai-writing, MIT license): the
``PATTERN_TABLES`` export of its detector, bundled in
``data/avoid_ai_writing.json`` by ``scripts/sync_avoid_ai_writing.py``. Each
pattern type becomes a check named ``ai-<type>`` in the ``ai-writing``
category, so ``--disable ai-writing`` turns them all off.

Most types are plain regular expressions. A few carry a *gate* upstream: a rule
on top of the table (a word must cluster in a paragraph, a phrase must repeat).
:data:`TYPE_GATES` and :data:`ENTRY_GATES` list the gates implemented here, by
their exact upstream wording. When a sync brings a gate that is not in these
tables, the type or entry is left out (and the tests fail) until the new
behaviour is implemented.
"""

from __future__ import annotations

import json
import math
from importlib import resources

import regex

from ..text import split_sentences, word_count
from . import ProjectCheck, register

DATA = json.loads(resources.files("pystylecheck").joinpath("data/avoid_ai_writing.json").read_text(encoding="utf-8"))
SOURCE = DATA["source"]
LINK = SOURCE["repository"] + "/blob/main/references/patterns.md"
# Upstream's technical exemptions, plus terms with a technical meaning in the
# papers pystylecheck targets ("unpacking 6-bit values").
LOCAL_EXEMPT = {"unpack", "unpacks", "unpacked", "unpacking"}
TECHNICAL_EXEMPT = frozenset(DATA.get("technical_exempt", ())) | LOCAL_EXEMPT

PROSE_KINDS = ("paragraph", "item", "footnote", "caption", "heading", "title", "cell")

TYPE_GATES = {
    "tier1": "`words` match whole lowercase tokens split on [\\w'-]+, so hyphenated and possessive forms do not count. The `technical` context skips TECHNICAL_EXEMPT terms.",
    "tier2": "Reported only when two or more distinct listed words share a paragraph. The `technical` context skips TECHNICAL_EXEMPT terms.",
    "tier3": "Reported only at max(3, floor(words * 0.03)) uses of one word; hyphenated words also match their dashless form.",
    "tier3-phrase": "Reported only at the second non-overlapping use of one phrase.",
    "tier3-phrase-cluster": "Reported only when three or more distinct phrases appear.",
    "confidence-calibration": "Reported only when three or more matches occur in one text.",
    # code, paths and URLs are already masked in the prose pystylecheck sees
    "unnecessary-hyphenation": "Runs on text with file paths, package names and code identifiers masked (maskHyphenationProtected).",
}
NP_GATE = "Reported only when another negative-parallelism frame starts within two sentences in the same paragraph."
ENTRY_GATES = {("negative-parallelism", NP_GATE)}
# Gated entries left out on purpose: the gate needs more than prose and regexes.
ENTRY_LEFT_OUT = {("tier1-clarity", 'Skipped where "features" reads as a noun (featuresIsNoun).')}

# Upstream severities target blog posts and chat replies. In a paper,
# "studies show~\cite{x}" is a sourced claim.
SEVERITY_OVERRIDES = {"vague-attribution": "warning"}

_FLAGS = {"i": regex.IGNORECASE, "m": regex.MULTILINE, "s": regex.DOTALL}
_TOKEN = regex.compile(r"[\w'-]+")


def compile_entry(e: dict) -> regex.Pattern:
    flags = regex.V0
    for c in e.get("flags", ""):
        flags |= _FLAGS.get(c, 0)
    return regex.compile(e["source"], flags)


def check_id(type_name: str) -> str:
    return type_name if type_name.startswith("ai-") else "ai-" + type_name


def skipped() -> list[str]:
    """Types and entries left out because their upstream gate is new to pystylecheck."""
    out = []
    for name, t in DATA["types"].items():
        if "gate" in t and TYPE_GATES.get(name) != t["gate"]:
            out.append(f"{name}: {t['gate']}")
        for e in t.get("patterns", []):
            if "gate" in e and (name, e["gate"]) not in ENTRY_GATES | ENTRY_LEFT_OUT:
                out.append(f"{name} /{e['source']}/: {e['gate']}")
    return out


def _short(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _dedupe(spans: list[tuple]) -> list[tuple]:
    """Drop matches inside an earlier, longer match (spans start with (i, j))."""
    out: list[tuple] = []
    for sp in sorted(spans, key=lambda s: (s[0], -s[1])):
        if out and sp[1] <= out[-1][1] and sp[0] >= out[-1][0]:
            continue
        out.append(sp)
    return out


class AIWritingCheck(ProjectCheck):
    category = "ai-writing"
    origin = "avoid-ai-writing"
    languages = frozenset({"en"})
    type_name = ""
    table: dict = {}

    # -- helpers ---------------------------------------------------------------
    def entries(self) -> list[tuple[regex.Pattern, dict]]:
        out = []
        for e in self.table.get("patterns", []):
            if "gate" in e and (self.type_name, e["gate"]) not in ENTRY_GATES:
                continue
            out.append((compile_entry(e), e))
        return out

    def blocks(self, docs):
        for d in docs:
            for b in d.prose_blocks(*PROSE_KINDS):
                yield d, b

    def report(self, ctx, doc, block, i, j, note: str = "", replace: str | None = None):
        s, e = block.span(i, j)
        msg = f"{self.table['label']}: '{_short(doc.source[s:e])}'"
        if note:
            msg += f" {note}"
        if replace:
            msg += f" (try: {replace})"
        return ctx.at_prose(self, doc, block, i, j, msg)

    def matches(self, block) -> list[tuple[int, int, dict]]:
        spans = []
        for rx, e in self.entries():
            for m in rx.finditer(block.text):
                if m.end() > m.start():
                    spans.append((m.start(), m.end(), e))
        return _dedupe(spans)

    # -- default: every match is a finding -------------------------------------
    def check_project(self, docs, ctx):
        for d, b in self.blocks(docs):
            for i, j, e in self.matches(b):
                yield self.report(ctx, d, b, i, j, replace=e.get("replace"))


class Tier1(AIWritingCheck):
    """Listed words (as whole tokens) and phrases; technical terms are exempt."""

    def check_project(self, docs, ctx):
        words = {w["word"]: w.get("replace") for w in self.table.get("words", [])}
        for d, b in self.blocks(docs):
            spans = [(i, j, e) for i, j, e in self.matches(b) if b.text[i:j].lower() not in TECHNICAL_EXEMPT]
            for m in _TOKEN.finditer(b.text):
                t = m.group().lower()
                if t in words and t not in TECHNICAL_EXEMPT:
                    spans.append((m.start(), m.end(), {"replace": words[t]}))
            for i, j, e in _dedupe(spans):
                yield self.report(ctx, d, b, i, j, replace=e.get("replace"))


class Tier2(AIWritingCheck):
    """Listed words, reported when two distinct ones share a paragraph."""

    def check_project(self, docs, ctx):
        words = {w["word"]: w.get("replace") for w in self.table.get("words", [])}
        for d, b in self.blocks(docs):
            hits: dict[str, list[tuple[int, int]]] = {}
            for m in _TOKEN.finditer(b.text):
                t = m.group().lower()
                if t in words and t not in TECHNICAL_EXEMPT:
                    hits.setdefault(t, []).append((m.start(), m.end()))
            for rx, e in self.entries():  # conditional words ("deeply rooted")
                w = e.get("word", "")
                if w in TECHNICAL_EXEMPT or w in hits:
                    continue
                for m in rx.finditer(b.text):
                    hits.setdefault(w, []).append((m.start(), m.end()))
                    words.setdefault(w, e.get("replace"))
            if len(hits) < 2:
                continue
            for w, spans in hits.items():
                others = ", ".join(f"'{o}'" for o in hits if o != w)
                for i, j in spans:
                    yield self.report(ctx, d, b, i, j, note=f"in the same paragraph as {others}", replace=words.get(w))


class Tier3(AIWritingCheck):
    """Listed words used at a high density in the whole document."""

    def check_project(self, docs, ctx):
        lookup = {}
        for w in self.table.get("words", []):
            lookup[w] = w
            lookup.setdefault(w.replace("-", ""), w)
        total = 0
        hits: dict[str, list] = {}
        for d, b in self.blocks(docs):
            total += word_count(b.text)
            for m in _TOKEN.finditer(b.text):
                w = lookup.get(m.group().lower())
                if w:
                    hits.setdefault(w, []).append((d, b, m.start(), m.end()))
        threshold = max(3, math.floor(total * 0.03))
        for w, occ in hits.items():
            if len(occ) >= threshold:
                for d, b, i, j in occ:
                    yield self.report(ctx, d, b, i, j, note=f"used {len(occ)} times in {total} words")


def _phrase_uses(check: AIWritingCheck, docs) -> list[list[tuple]]:
    """Non-overlapping uses of each boilerplate phrase, in table order."""
    claimed: dict[tuple[str, int], list[tuple[int, int]]] = {}
    out = []
    for rx, e in check.entries():
        uses = []
        for d, b in check.blocks(docs):
            taken = claimed.setdefault((d.path, id(b)), [])
            for m in rx.finditer(b.text):
                if not any(m.start() < y and m.end() > x for x, y in taken):
                    uses.append((d, b, m.start(), m.end()))
        for d, b, i, j in uses:
            claimed[(d.path, id(b))].append((i, j))
        if uses:
            out.append(uses)
    return out


class Tier3Phrase(AIWritingCheck):
    """A boilerplate phrase used twice or more."""

    def check_project(self, docs, ctx):
        for uses in _phrase_uses(self, docs):
            if len(uses) >= 2:
                for d, b, i, j in uses:
                    yield self.report(ctx, d, b, i, j, note=f"used {len(uses)} times")


class Tier3PhraseCluster(AIWritingCheck):
    """Three or more distinct boilerplate phrases."""

    def check_project(self, docs, ctx):
        found = _phrase_uses(self, docs)
        if len(found) >= 3:
            for uses in found:
                d, b, i, j = uses[0]
                yield self.report(ctx, d, b, i, j, note=f"one of {len(found)} distinct boilerplate phrases")


class ConfidenceCalibration(AIWritingCheck):
    """Confidence words, reported when three or more occur."""

    def check_project(self, docs, ctx):
        occ = [(d, b, i, j) for d, b in self.blocks(docs) for i, j, _ in self.matches(b)]
        if len(occ) >= 3:
            for d, b, i, j in occ:
                yield self.report(ctx, d, b, i, j, note=f"one of {len(occ)} confidence markers")


class NegativeParallelism(AIWritingCheck):
    """'It isn't just X, it's Y'. Gated frames need another frame within two sentences."""

    def check_project(self, docs, ctx):
        for d, b in self.blocks(docs):
            frames = []  # (start, end, gated)
            for e in self.table.get("patterns", []):
                gated = "gate" in e
                if gated and (self.type_name, e["gate"]) not in ENTRY_GATES:
                    continue
                for m in compile_entry(e).finditer(b.text):
                    frames.append((m.start(), m.end(), gated))
            if not frames:
                continue
            starts = [s.start for s in split_sentences(b.text, d.language)] or [0]

            def sentence_of(i: int) -> int:
                return max([k for k, s in enumerate(starts) if s <= i], default=0)

            seen = set()
            for i, j, gated in sorted(frames):
                if i in seen:
                    continue
                if gated and not any(
                    o != i and abs(sentence_of(o) - sentence_of(i)) <= 2 for o, _, _ in frames
                ):
                    continue
                seen.add(i)
                yield self.report(ctx, d, b, i, j)


SPECIAL = {
    "tier1": Tier1,
    "tier2": Tier2,
    "tier3": Tier3,
    "tier3-phrase": Tier3Phrase,
    "tier3-phrase-cluster": Tier3PhraseCluster,
    "confidence-calibration": ConfidenceCalibration,
    "negative-parallelism": NegativeParallelism,
}


def _explanation(name: str, t: dict) -> str:
    parts = [f"{t['label']}: a pattern common in AI-generated text, from the avoid-ai-writing catalog "
             f"(version {SOURCE['version']}, {LINK})."]
    words = [w["word"] if isinstance(w, dict) else w for w in t.get("words", [])]
    if words:
        parts.append("Words: " + ", ".join(words[:12]) + (", ..." if len(words) > 12 else "") + ".")
    if "gate" in t:
        parts.append(t["gate"])
    if name in ("tier1", "tier2"):
        parts.append("Technical terms (robust, leverage, ecosystem, unpack...) are not flagged.")
    parts.append("These are hints, not errors: rewrite when a plainer word says the same. "
                 "Turn all of them off with --disable ai-writing.")
    return " ".join(parts)


def _register_all() -> None:
    for name, t in DATA["types"].items():
        if "gate" in t and TYPE_GATES.get(name) != t["gate"]:
            continue  # upstream gate not implemented yet: see skipped()
        if not t.get("patterns") and not t.get("words"):
            continue
        base = SPECIAL.get(name, AIWritingCheck)
        cls = type(
            "AI_" + name.replace("-", "_"),
            (base,),
            {
                "id": check_id(name),
                "type_name": name,
                "table": t,
                "description": f"{t['label']} (avoid-ai-writing)",
                "explanation": _explanation(name, t),
                "severity": SEVERITY_OVERRIDES.get(name) or t.get("severity") or "info",
            },
        )
        register(cls)


_register_all()
