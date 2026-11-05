"""Command line interface."""

from __future__ import annotations

import argparse
import os
import sys
import textwrap

from . import __version__
from .checks import all_checks
from .config import load_options, read_style_checkrc

EPILOG = """\
pystylecheck is a superset of style-check.rb: it reads the same rule files
(~/.style-check.d/*, ~/.style-censor, ./style-censor, /etc/style-check.d/*...)
and understands LaTeX, so rules see the prose and not the markup.

Inline control, in LaTeX comments:
  % pystylecheck: ignore                 (this line)
  % pystylecheck: ignore=duplicate-word  (this line, one check)
  % pystylecheck: ignore-next-line
  % pystylecheck: disable=long-sentence ... % pystylecheck: enable=long-sentence

Subcommands:
  pystylecheck mcp            run as an MCP server (for AI agents)
  pystylecheck mcp --setup    print commands registering it with agents

Exit status: 1 if an error was found (or a warning, with -W), 0 otherwise.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pystylecheck",
        description="Check LaTeX documents for style problems.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("files", nargs="*", help="LaTeX files to check ('-' reads standard input)")
    p.add_argument("--version", action="version", version=f"pystylecheck {__version__}")
    g = p.add_argument_group("style-check.rb options")
    g.add_argument("-g", "--gedit", action="store_true", help="put a space between line and column (for gedit)")
    g.add_argument("-v", "--verbose", action="count", default=0, help="explain each rule the first time it matches; -vv: every time")
    g.add_argument("-w", "--web-output", action="store_true", help="generate an HTML report")
    g.add_argument("-r", "--override-rule-paths", action="append", metavar="PATH", default=[],
                   help="use only these rule files or directories")
    g = p.add_argument_group("selection")
    g.add_argument("-l", "--lang", "--language", dest="language", choices=["auto", "en", "fr"], help="document language (default: from babel/polyglossia, else guessed)")
    g.add_argument("-e", "--enable", action="append", default=[], metavar="ID", help="enable a check, a category or a rule kind (repeatable, comma-separated)")
    g.add_argument("-d", "--disable", action="append", default=[], metavar="ID",
                   help="disable a check, a category, a rule kind (phrase, spelling...) or a rule file (@passive-voice)")
    g.add_argument("--only", action="append", default=[], metavar="ID", help="run only these checks")
    g.add_argument("--compat", action="store_true", help="behave like style-check.rb: only its rules and built-in checks")
    g.add_argument("--rules", action="append", default=[], metavar="PATH", help="additional rule file or directory")
    g.add_argument("--no-default-rules", action="store_true", help="do not load the bundled rule files")
    g.add_argument("--no-user-rules", action="store_true", help="do not load ~/.style-check.d and the other style-check locations")
    g.add_argument("--plugin", action="append", default=[], metavar="MODULE", help="load checks from a Python module or .py file")
    g.add_argument("--min-severity", choices=["error", "warning", "info"], help="hide findings below this severity")
    g.add_argument("--no-follow-includes", action="store_true", help="do not check files pulled in by \\input and \\include")
    g.add_argument("--config", metavar="FILE", help="configuration file (default: .pystylecheck.toml found upward)")
    g = p.add_argument_group("output")
    g.add_argument("-f", "--format", choices=["text", "json", "html", "github", "style-check"], help="output format")
    g.add_argument("--no-context", action="store_true", help="do not print the source line under each finding")
    g.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    g.add_argument("-W", "--warnings-as-errors", action="store_true", help="exit with status 1 on warnings too")
    g.add_argument("--fix", action="store_true", help="apply the safe fixes in place")
    g.add_argument("--diff", action="store_true", help="print the safe fixes as a unified diff (no change)")
    g = p.add_argument_group("information")
    g.add_argument("--list-checks", action="store_true", help="list the checks and exit")
    g.add_argument("--list-rules", action="store_true", help="list the loaded rule files and exit")
    g.add_argument("--explain", metavar="ID", help="explain a check and exit")
    return p


def _split(values: list[str]) -> list[str]:
    return [x.strip() for v in values for x in v.split(",") if x.strip()]


def list_checks(lang: str | None = None) -> list[dict]:
    out = []
    for cid, cls in sorted(all_checks().items()):
        c = cls()
        if lang and not c.applies_to(lang):
            continue
        out.append(
            {
                "id": cid,
                "description": c.description,
                "category": c.category,
                "severity": c.severity,
                "languages": sorted(c.languages) if c.languages else ["all"],
                "origin": c.origin,
                "enabled_by_default": c.default_enabled,
                "fixable": c.fixable,
            }
        )
    return out


def explain(check_id: str) -> str | None:
    cls = all_checks().get(check_id)
    if cls is None:
        return None
    c = cls()
    langs = ", ".join(sorted(c.languages)) if c.languages else "all languages"
    lines = [f"{c.id}: {c.description}", "", textwrap.fill(c.explanation or c.description, 78), "",
             f"severity: {c.severity}; category: {c.category}; applies to: {langs}; from: {c.origin}"
             + ("; has safe fixes" if c.fixable else "")]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "mcp":
        from .mcp_server import main as mcp_main

        return mcp_main(argv[1:])

    args = build_parser().parse_args(argv)
    start = args.files[0] if args.files and args.files[0] != "-" else os.getcwd()
    opts, warnings = load_options(start, args.config)

    rc = read_style_checkrc()
    gedit = args.gedit or bool(rc.get("gedit"))
    verbose = args.verbose or (2 if rc.get("really_verbose") else 1 if rc.get("verbose") else 0)
    web = args.web_output or bool(rc.get("web_output"))
    if not args.override_rule_paths and isinstance(rc.get("override_rule_paths"), str):
        args.override_rule_paths = [rc["override_rule_paths"]]

    if args.language:
        opts.language = args.language
    opts.enable += _split(args.enable)
    opts.disable += _split(args.disable)
    opts.only += _split(args.only)
    opts.rules += args.rules
    opts.plugins += args.plugin
    if args.override_rule_paths:
        for pth in args.override_rule_paths:
            if not os.path.exists(pth):
                print(f"Could not find rule file or directory at {pth}", file=sys.stderr)
                return 1
        opts.override_rules = args.override_rule_paths
    if args.no_default_rules:
        opts.default_rules = False
    if args.no_user_rules:
        opts.user_rules = False
    if args.compat:
        opts.compat = True
    if args.min_severity:
        opts.min_severity = args.min_severity
    if args.no_follow_includes:
        opts.follow_includes = False
    if args.warnings_as_errors:
        opts.warnings_as_errors = True

    if args.list_checks:
        for c in list_checks():
            langs = ",".join(c["languages"])
            off = "" if c["enabled_by_default"] else " (off by default)"
            print(f"{c['id']:28} {c['severity']:8} {langs:4} {c['description']}{off}")
        return 0
    if args.explain:
        text = explain(args.explain)
        if text is None:
            print(f"unknown check '{args.explain}' (see --list-checks)", file=sys.stderr)
            return 2
        print(text)
        return 0

    from .engine import StyleChecker, apply_fixes, unified_diff
    from . import output

    checker = StyleChecker(opts)
    if args.list_rules:
        for f in checker.rules.files:
            n = sum(r.file == f for r in checker.rules.rules)
            print(f"{f}: {n} rules")
        return 0
    if not args.files:
        build_parser().print_usage(sys.stderr)
        print("pystylecheck: no input files (try --help)", file=sys.stderr)
        return 2

    report = checker.check_paths(args.files)
    for m in warnings + report.messages:
        print(m, file=sys.stderr)

    if args.fix or args.diff:
        changes = apply_fixes(report)
        if args.diff:
            sys.stdout.write(unified_diff(changes))
        if args.fix:
            for path, (_, new) in changes.items():
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)
            n = sum(1 for f in report.findings if f.replacement is not None)
            print(f"pystylecheck: fixed {len(changes)} file(s); {n} finding(s) had a safe fix", file=sys.stderr)
        return report.exit_status(opts.warnings_as_errors) if args.diff else 0

    fmt = args.format or ("html" if web else "style-check" if opts.compat else "text")
    if opts.min_severity is None and fmt == "text":
        # notes (long sentences, short sections...) are advice: hide them unless asked
        notes = [f for f in report.findings if f.severity == "info"]
        report.findings = [f for f in report.findings if f.severity != "info"]
        report.hidden["info"] = report.hidden.get("info", 0) + len(notes)
    if fmt == "json":
        sys.stdout.write(output.format_json(report))
    elif fmt == "html":
        sys.stdout.write(output.format_html(report))
    elif fmt == "github":
        sys.stdout.write(output.format_github(report))
    elif fmt == "style-check":
        sys.stdout.write(output.format_style_check(report, verbose, gedit))
    else:
        color = args.color == "always" or (args.color == "auto" and output.use_color())
        sys.stdout.write(output.format_text(report, verbose, gedit, color, not args.no_context))
        s = report.summary()
        hidden = report.hidden.get("info", 0)
        if report.findings and sys.stdout.isatty():
            print(f"{s['findings']} finding(s): {s['error']} error(s), {s['warning']} warning(s), {s['info']} note(s)", file=sys.stderr)
        if hidden and opts.min_severity is None:
            print(f"pystylecheck: {hidden} note(s) hidden (long sentences, short sections...): use --min-severity info to see them",
                  file=sys.stderr)
    return report.exit_status(opts.warnings_as_errors)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
