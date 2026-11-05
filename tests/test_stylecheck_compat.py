"""pystylecheck --compat reproduces style-check.rb exactly on its own test files."""

import os
import subprocess
import sys
from pathlib import Path

DATA = Path(__file__).parent / "data" / "style-check"
RULES = Path(__file__).parent.parent / "src" / "pystylecheck" / "rules" / "en"


def run_cli(*args, cwd=DATA):
    env = dict(os.environ, NO_COLOR="1")
    return subprocess.run([sys.executable, "-m", "pystylecheck", *args], cwd=cwd, capture_output=True, text=True, env=env)


def test_dirty_matches_style_check_rb():
    # dirty.expected is the output of: style-check.rb -r rules dirty.tex
    p = run_cli("--compat", "--no-user-rules", "-r", str(RULES), "dirty.tex")
    assert p.returncode == 1
    got = sorted(p.stdout.splitlines())
    expected = sorted((DATA / "dirty.expected").read_text().splitlines())
    assert got == expected


def test_clean_and_math_report_nothing():
    p = run_cli("--compat", "--no-user-rules", "-r", str(RULES), "clean.tex", "math.tex")
    assert p.returncode == 0
    assert p.stdout == ""


def test_gedit_and_web_output():
    p = run_cli("--compat", "--no-user-rules", "-g", "-r", str(RULES), "dirty.tex")
    assert "dirty.tex:1: 32:" in p.stdout
    p = run_cli("--compat", "--no-user-rules", "-w", "-r", str(RULES), "dirty.tex")
    assert "<html" in p.stdout


def test_full_mode_catches_every_dirty_line():
    """The default mode is a superset: every line style-check flags is still flagged."""
    p = run_cli("--no-user-rules", "-f", "json", "dirty.tex")
    import json

    lines = {f["line"] for f in json.loads(p.stdout)["findings"]}
    expected = {int(l.split(":")[1]) for l in (DATA / "dirty.expected").read_text().splitlines()}
    assert expected <= lines


def test_full_mode_clean_file_has_no_errors():
    p = run_cli("--no-user-rules", "--min-severity", "error", "clean.tex", "math.tex")
    assert p.returncode == 0, p.stdout
