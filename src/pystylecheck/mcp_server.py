"""MCP server: lets AI agents (Claude Code, Codex, Gemini CLI, Cursor...) run pystylecheck."""

from __future__ import annotations

import os
import shlex
import sys
from typing import Any

INSTRUCTIONS = """\
pystylecheck checks LaTeX documents (papers, reports, theses) for style problems:
verbose or weak phrases, spelling and capitalization slips, repeated words, headings
not followed by text, citation and reference spacing, figure and table conventions,
math typography and, for French documents, French typography.

Use check_latex on .tex files (it follows \\input and \\include from a main file, so
pass the main file to check a whole thesis). Findings have a severity: 'error' is
almost always a real problem; 'warning' deserves a look; 'info' is advice. Rule-based
findings are suggestions about style, not mandates: keep the author's voice and do not
rewrite text that is correct. Many findings carry a 'replacement' that is a safe,
mechanical fix (fix_latex applies them). Use explain_check for the rationale of a check.
To silence a false positive, add '% pystylecheck: ignore=<check>' at the end of the line.
"""


def _report_dict(report, max_findings: int) -> dict[str, Any]:
    findings = [f.to_dict() for f in report.findings]
    for f in findings:
        f.pop("start", None)
        f.pop("end", None)
    truncated = len(findings) > max_findings
    return {
        "summary": report.summary(),
        "findings": findings[:max_findings],
        "truncated": truncated,
        "messages": report.messages,
        "files": [d.path for d in report.documents],
        "languages": {d.path: d.language for d in report.documents},
    }


def run_check(
    paths: list[str] | None = None,
    text: str | None = None,
    filename: str | None = None,
    language: str = "auto",
    enable: list[str] | None = None,
    disable: list[str] | None = None,
    only: list[str] | None = None,
    min_severity: str = "info",
    follow_includes: bool = True,
    compat: bool = False,
):
    from .config import load_options
    from .engine import StyleChecker

    start = (paths[0] if paths else filename) or os.getcwd()
    opts, warnings = load_options(start)
    opts.language = language or "auto"
    opts.enable += list(enable or [])
    opts.disable += list(disable or [])
    opts.only += list(only or [])
    opts.min_severity = min_severity or "info"
    opts.follow_includes = follow_includes
    opts.compat = compat
    checker = StyleChecker(opts)
    if text is not None:
        report = checker.check_text(text, filename or "<text>")
    else:
        missing = [p for p in paths or [] if not os.path.isfile(p)]
        if missing:
            raise ValueError(f"file not found: {', '.join(missing)} (use absolute paths)")
        report = checker.check_paths(list(paths or []))
    report.messages = warnings + report.messages
    return report


def build_server():
    try:
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP as Server

    from . import __version__
    from .cli import explain, list_checks
    from .engine import apply_fixes, unified_diff

    server = Server("pystylecheck", instructions=INSTRUCTIONS, version=__version__) if _accepts_version(Server) else Server("pystylecheck", instructions=INSTRUCTIONS)

    @server.tool()
    def check_latex(
        paths: list[str] | None = None,
        text: str | None = None,
        filename: str | None = None,
        language: str = "auto",
        enable: list[str] | None = None,
        disable: list[str] | None = None,
        only: list[str] | None = None,
        min_severity: str = "info",
        follow_includes: bool = True,
        max_findings: int = 300,
    ) -> dict[str, Any]:
        """Check LaTeX files for style problems and return the findings.

        paths: absolute paths of .tex files (give the main file to check a whole document;
        \\input/\\include are followed unless follow_includes is false). Or pass the LaTeX
        source in `text` (with an optional `filename` used in the report).
        language: 'auto' (from babel/polyglossia, else guessed), 'en' or 'fr'.
        enable/disable/only: check ids (see list_checks), categories, rule kinds
        ('phrase', 'spelling', 'capitalize', 'syntax') or rule files ('@passive-voice').
        min_severity: 'error', 'warning' or 'info'.
        Each finding has path, line, column, end_line, end_column, severity, check,
        message, the matched text and, when a safe fix exists, a 'replacement' for the
        matched source text.
        """
        if not paths and text is None:
            raise ValueError("give paths or text")
        report = run_check(paths, text, filename, language, enable, disable, only, min_severity, follow_includes)
        return _report_dict(report, max_findings)

    @server.tool()
    def fix_latex(
        paths: list[str],
        checks: list[str] | None = None,
        dry_run: bool = True,
        language: str = "auto",
    ) -> dict[str, Any]:
        """Apply pystylecheck's safe, mechanical fixes (non-breaking spaces before \\ref
        and \\cite, repeated words, \\sin in math...).

        With dry_run (the default) nothing is written: the unified diff is returned so it
        can be reviewed. checks: restrict to these check ids. Files are only rewritten
        when dry_run is false.
        """
        report = run_check(paths, language=language, follow_includes=False)
        changes = apply_fixes(report, set(checks) if checks else None)
        if not dry_run:
            for path, (_, new) in changes.items():
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)
        return {"diff": unified_diff(changes), "files_changed": sorted(changes), "written": not dry_run}

    @server.tool()
    def list_style_checks(language: str | None = None) -> list[dict[str, Any]]:
        """List the available checks (id, description, severity, languages, origin).
        language: 'en' or 'fr' to keep only the checks that apply to it."""
        return list_checks(language)

    @server.tool()
    def explain_check(check_id: str) -> str:
        """Explain what a check looks for and why (use the 'check' field of a finding)."""
        text = explain(check_id)
        if text is None:
            if check_id in ("phrase", "spelling", "capitalize", "syntax", "prose"):
                return explain("rules") or ""
            raise ValueError(f"unknown check '{check_id}'")
        return text

    return server


def _accepts_version(cls) -> bool:
    import inspect

    try:
        return "version" in inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        return False


SETUP = """\
Register pystylecheck as an MCP server (stdio) in your agent.  {cmd}

Claude Code:
  claude mcp add --scope user --transport stdio pystylecheck -- {cmd}
OpenAI Codex CLI:
  codex mcp add pystylecheck -- {cmd}
Google Gemini CLI:
  gemini mcp add --scope user pystylecheck {cmd}
xAI Grok CLI:
  grok mcp add pystylecheck -- {cmd}
Cursor:
  cursor --add-mcp '{{"name":"pystylecheck","command":"{exe}","args":{args}}}'
VS Code (Copilot agent mode):
  code --add-mcp '{{"name":"pystylecheck","command":"{exe}","args":{args}}}'
Other clients (JSON configuration):
  {{"mcpServers": {{"pystylecheck": {{"command": "{exe}", "args": {args}}}}}}}
"""


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    if "--setup" in argv:
        import json
        import shutil

        exe = shutil.which("pystylecheck")
        if exe and ("/.cache/uv/" in exe or "archive-v" in exe or "/uv/cache/" in exe):
            exe = None  # a temporary uvx environment: register the uvx command instead
        if exe:
            parts = [exe, "mcp"]
        else:
            parts = ["uvx", "--from", "git+https://github.com/lemire/pystylecheck", "pystylecheck", "mcp"]
        print(SETUP.format(cmd=" ".join(shlex.quote(p) for p in parts), exe=parts[0], args=json.dumps(parts[1:])))
        return 0
    if "-h" in argv or "--help" in argv:
        print("usage: pystylecheck mcp [--setup]\n\nRun the MCP server over stdio; --setup prints registration commands.")
        return 0
    server = build_server()
    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
