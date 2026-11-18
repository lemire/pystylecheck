"""The ai-* checks generated from avoid-ai-writing."""

import regex

from pystylecheck.checks import all_checks
from pystylecheck.checks.aiwriting import DATA, check_id, compile_entry, skipped
from pystylecheck.cli import main


def ai(findings, cid=None):
    return [f for f in findings if f.check.startswith("ai-") and (cid is None or f.check == cid)]


# -- the bundled data ------------------------------------------------------------------

def test_every_upstream_gate_is_handled():
    # Fails after a sync that brings a gate pystylecheck does not implement:
    # implement it in checks/aiwriting.py, then add it to TYPE_GATES or ENTRY_GATES.
    assert skipped() == []


def test_every_pattern_compiles():
    for name, t in DATA["types"].items():
        for e in t.get("patterns", []):
            assert isinstance(compile_entry(e), regex.Pattern), (name, e["source"])


def test_every_type_is_a_check():
    checks = all_checks()
    for name, t in DATA["types"].items():
        if t.get("patterns") or t.get("words"):
            c = checks[check_id(name)]
            assert c.category == "ai-writing" and c.severity in ("error", "warning", "info")


def test_source_is_recorded():
    src = DATA["source"]
    assert src["repository"].endswith("/avoid-ai-writing") and src["license"] == "MIT"


# -- behaviour ---------------------------------------------------------------------------

def test_chatbot_artifact_is_an_error(check):
    fs = ai(check("The results are good. I hope this helps.\n"), "ai-chatbot")
    assert len(fs) == 1 and fs[0].severity == "error" and fs[0].column == 23


def test_matches_across_lines_and_markup(check):
    fs = ai(check("We \\emph{delve}\ninto the details.\n"), "ai-tier1")
    assert [f.line for f in fs] == [1]
    assert "explore" in fs[0].message


def test_tier1_skips_technical_terms(check):
    assert not ai(check("A robust hash function. We leverage SIMD. Unpacking 6-bit values.\n"), "ai-tier1")
    assert ai(check("This paradigm is a tapestry of ideas.\n"), "ai-tier1")


def test_tier2_needs_two_words_in_a_paragraph(check):
    assert not ai(check("This step is crucial.\n\nWe foster reuse.\n"), "ai-tier2")
    fs = ai(check("This step is crucial. We foster reuse.\n"), "ai-tier2")
    assert len(fs) == 2


def test_tier3_density(check):
    assert not ai(check("A significant gain. A significant cost.\n"), "ai-tier3")
    assert len(ai(check("A significant gain, a significant cost, a significant risk.\n"), "ai-tier3")) == 3


def test_confidence_markers_must_stack(check):
    assert not ai(check("Interestingly, it works. Surprisingly, it is fast.\n"), "ai-confidence-calibration")
    fs = ai(check("Interestingly, it works. Surprisingly, it is fast. Importantly, it is small.\n"))
    assert len([f for f in fs if f.check == "ai-confidence-calibration"]) == 3


def test_negative_parallelism_contrast_needs_a_second_frame(check):
    assert not ai(check("It isn't raining, it's snowing.\n"), "ai-negative-parallelism")
    fs = ai(check("It isn't raining, it's snowing. It isn't cold, it's freezing.\n"), "ai-negative-parallelism")
    assert len(fs) == 2


def test_variable_width_lookbehind(check):
    # upstream uses lookbehinds that Python's re module rejects
    assert ai(check("We tested it. Turns out the cache was cold.\n"), "ai-performed-insight")


def test_not_in_math_code_comments_or_french(check):
    src = "Use \\texttt{I hope this helps} and $moreover$. % I hope this helps\n"
    assert not ai(check(src))
    assert not ai(check("I hope this helps.\n", language="fr"))


def test_disable_the_family(check):
    src = "I hope this helps. Moreover, we delve into it.\n"
    assert ai(check(src))
    assert not ai(check(src, disable=["ai-writing"]))
    assert not ai(check(src, compat=True))


def test_listed_and_explained(capsys):
    assert main(["--explain", "ai-tier2"]) == 0
    out = capsys.readouterr().out
    assert "avoid-ai-writing" in out and "two or more distinct" in out
