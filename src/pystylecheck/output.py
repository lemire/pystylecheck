"""Report formatting."""

from __future__ import annotations

import html
import json
import os
import sys

from . import __version__
from .engine import Report
from .findings import Finding

COLORS = {"error": "\033[31m", "warning": "\033[33m", "info": "\033[36m"}
BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


def _excerpt(f: Finding) -> tuple[str, str]:
    """The source line, tabs expanded, and a caret line under the match."""
    line = f.excerpt.replace("\t", " ")
    start = f.column - 1
    if f.end_line == f.line:
        width = max(1, f.end_column - f.column)
    else:
        width = max(1, len(line) - start)
    return line, " " * start + "^" + "~" * (width - 1)


def format_text(report: Report, verbose: int = 0, gedit: bool = False, color: bool = False, context: bool = True) -> str:
    out = []
    explained: set[str] = set()
    for f in report.findings:
        sep = " " if gedit else ""
        sev = f.severity
        if color:
            head = f"{BOLD}{f.path}:{f.line}:{sep}{f.column}:{RESET} {COLORS.get(sev, '')}{sev}:{RESET} {f.message} {DIM}[{f.check}]{RESET}"
        else:
            head = f"{f.path}:{f.line}:{sep}{f.column}: {sev}: {f.message} [{f.check}]"
        out.append(head)
        if context and f.excerpt.strip():
            line, caret = _excerpt(f)
            if len(line) > 160:
                a = max(0, f.column - 60)
                line, caret = "…" + line[a : a + 150], " " + caret[a : a + 150]
            out.append("    " + line)
            out.append("    " + (COLORS.get(sev, "") + caret + RESET if color else caret))
        key = f.rule_source or f.check
        if verbose and (verbose > 1 or key not in explained):
            explained.add(key)
            expl = f.explanation.strip()
            if expl and expl != f.message:
                out.append("    " + expl)
            if f.rule_source:
                out.append(f"    (matched '{f.matched}' with {f.rule_source})")
    return "\n".join(out) + ("\n" if out else "")


def format_style_check(report: Report, verbose: int = 0, gedit: bool = False) -> str:
    """Exactly the output format of style-check.rb."""
    out = []
    explained: set[str] = set()
    for f in report.findings:
        problem = f.matched.replace("\n", " ")
        out.append("%s:%d:%s%d: %s (%s)" % (f.path, f.line, " " if gedit else "", f.column, f.excerpt, problem))
        key = f.rule_source or f.check
        if verbose and (verbose > 1 or key not in explained):
            explained.add(key)
            reason = (f.explanation or f.message).strip()
            src = f"  (matched '{f.matched}' in {f.rule_source})" if f.rule_source else ""
            out.append(" " + reason + src)
    return "\n".join(out) + ("\n" if out else "")


def format_json(report: Report) -> str:
    return json.dumps(
        {
            "tool": "pystylecheck",
            "version": __version__,
            "summary": report.summary(),
            "messages": report.messages,
            "findings": [f.to_dict() for f in report.findings],
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def _gh_escape(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def format_github(report: Report) -> str:
    out = []
    for f in report.findings:
        level = {"error": "error", "warning": "warning"}.get(f.severity, "notice")
        props = f"file={f.path},line={f.line},col={f.column},endLine={f.end_line},endColumn={f.end_column},title={f.check}"
        out.append(f"::{level} {_gh_escape(props)}::{_gh_escape(f.message)}")
    return "\n".join(out) + ("\n" if out else "")


_HTML_HEAD = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>pystylecheck report</title>
<style>
body{font:15px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:72rem;padding:0 1rem;color:#222}
h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:2rem;font-family:monospace}
.f{border-left:4px solid #ccc;padding:.4rem .8rem;margin:.6rem 0;background:#fafafa}
.error{border-color:#c62828}.warning{border-color:#ef8f00}.info{border-color:#1e88e5}
.loc{font-family:monospace;color:#555}.id{font-family:monospace;font-size:.85em;color:#777;margin-left:.5rem}
pre{margin:.3rem 0 0;white-space:pre-wrap;font-size:.9em}mark{background:#ffe08a}
.expl{color:#555;font-size:.9em;margin-top:.2rem}#filters label{margin-right:1rem}
.hidden{display:none}
</style></head><body>
<h1>pystylecheck report</h1>
<div id="filters"></div>
"""

_HTML_TAIL = """<script>
const sevs=['error','warning','info'];const box=document.getElementById('filters');
const counts={};document.querySelectorAll('.f').forEach(e=>{counts[e.dataset.sev]=(counts[e.dataset.sev]||0)+1});
sevs.forEach(s=>{if(!counts[s])return;const l=document.createElement('label');
l.innerHTML=`<input type=checkbox checked data-sev=${s}> ${s} (${counts[s]})`;box.appendChild(l)});
box.addEventListener('change',e=>{const s=e.target.dataset.sev;
document.querySelectorAll('.f.'+s).forEach(x=>x.classList.toggle('hidden',!e.target.checked))});
</script>
<p style="color:#777;font-size:.85em">Generated by pystylecheck, a superset of
<a href="http://www.cs.umd.edu/~nspring/software/style-check-readme.html">style-check.rb</a>.</p>
</body></html>
"""


def format_html(report: Report) -> str:
    parts = [_HTML_HEAD]
    current = None
    for f in report.findings:
        if f.path != current:
            current = f.path
            parts.append(f"<h2>{html.escape(f.path)}</h2>")
        line = f.excerpt
        a = f.column - 1
        b = f.end_column - 1 if f.end_line == f.line else len(line)
        shown = html.escape(line[:a]) + "<mark>" + html.escape(line[a:b]) + "</mark>" + html.escape(line[b:])
        expl = f'<div class="expl">{html.escape(f.explanation)}</div>' if f.explanation and f.explanation != f.message else ""
        parts.append(
            f'<div class="f {f.severity}" data-sev="{f.severity}"><span class="loc">line {f.line}, column {f.column}</span> '
            f"{html.escape(f.message)}<span class=\"id\">{html.escape(f.check)}</span><pre>{shown}</pre>{expl}</div>"
        )
    if not report.findings:
        parts.append("<p>No problems found.</p>")
    parts.append(_HTML_TAIL)
    return "".join(parts)


def use_color(stream=sys.stdout) -> bool:
    return hasattr(stream, "isatty") and stream.isatty() and os.environ.get("NO_COLOR") is None and os.environ.get("TERM") != "dumb"
