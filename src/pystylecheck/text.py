"""Helpers for prose: sentences and words."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .latexdb import PLACEHOLDER_CLASS, PLACEHOLDERS

ABBREVIATIONS = {
    "en": {
        "e.g", "i.e", "etc", "al", "cf", "vs", "resp", "approx", "fig", "figs", "eq", "eqs", "sec", "secs",
        "ch", "chap", "dr", "mr", "mrs", "ms", "prof", "no", "nos", "vol", "pp", "p", "ed", "eds", "inc",
        "ltd", "jr", "sr", "st", "dept", "univ", "thm", "def", "lem", "prop", "alg", "tab", "app", "ref",
        "refs", "viz", "ca", "est", "min", "max", "avg", "u.s", "ph.d", "m.sc", "b.sc", "a.k.a",
    },
    "fr": {
        "p. ex", "ex", "etc", "al", "cf", "c.-à-d", "c-à-d", "fig", "éq", "eq", "chap", "vol", "p", "pp",
        "m", "mm", "mme", "mmes", "mlle", "dr", "pr", "prof", "env", "av", "apr", "n°", "no", "réf", "sect",
        "tab", "art", "coll", "dir", "éd", "op", "cit", "ibid", "vs", "resp", "min", "max", "approx", "sq", "sqq",
    },
}

_WORD = re.compile(r"[^\W\d_](?:[\w'’-]*\w)?")


@dataclass
class Sentence:
    start: int  # index in the block text
    end: int

    def text(self, s: str) -> str:
        return s[self.start : self.end]


def split_sentences(text: str, lang: str = "en") -> list[Sentence]:
    """Split prose into sentences, aware of abbreviations, initials and numbers."""
    abbrevs = ABBREVIATIONS.get(lang, ABBREVIATIONS["en"]) | ABBREVIATIONS["en"]
    out: list[Sentence] = []
    start = 0
    n = len(text)
    for m in re.finditer(r"[.!?…]+[\"”»’')\]]*(?=[\s ]+|$)", text):
        end = m.end()
        punct_pos = m.start()
        inside = text[start:punct_pos]
        tail = m.group(0)
        # "(most?) of", "\ldots) to": the punctuation is inside brackets
        if (")" in tail and inside.count("(") > inside.count(")")) or ("]" in tail and inside.count("[") > inside.count("]")):
            continue
        if text[punct_pos] == ".":
            before = text[start:punct_pos]
            wm = re.search(r"([^\s (\[“«]+)$", before)
            word = wm.group(1) if wm else ""
            lw_ = word.lower().rstrip(".")
            if lw_ in abbrevs or len(word.strip("\u202f")) == 1 or re.fullmatch(r"(?:[^\W\d_]\.)+[^\W\d_]", word):
                continue
            # "p. ex." in French
            if lang == "fr" and re.search(r"\bp\.\s*ex$", before, re.I):
                continue
        if text[start:end].strip():
            out.append(Sentence(start, end))
        start = end
    if text[start:n].strip():
        out.append(Sentence(start, n))
    # trim leading whitespace from each sentence
    trimmed = []
    for s in out:
        k = s.start
        while k < s.end and (text[k].isspace() or text[k] == " "):
            k += 1
        trimmed.append(Sentence(k, s.end))
    return trimmed


def words(text: str) -> list[re.Match]:
    return list(_WORD.finditer(text))


def word_count(text: str) -> int:
    """Number of words; a formula or a citation counts as one word."""
    return len(_WORD.findall(text)) + sum(text.count(p) for p in PLACEHOLDERS)


def first_token(text: str) -> tuple[int, str] | None:
    """Index and text of the first word or placeholder, skipping quotes and brackets."""
    m = re.search(r"(" + PLACEHOLDER_CLASS + r"|[^\W_]+)", text)
    if not m:
        return None
    return m.start(), m.group(1)
