"""Run the checks over a set of files."""

from __future__ import annotations

import difflib
import os
import re
import sys
from dataclasses import dataclass, field

from . import latexdb
from .checks import Check, Context, ProjectCheck, all_checks, load_plugin
from .config import Options
from .findings import SEVERITY_RANK, Finding
from .latex import Document, parse
from .rules import RuleSet, load_rules

RULE_KINDS = {"phrase", "spelling", "capitalize", "syntax", "prose"}


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)  # warnings about the run itself
    hidden: dict[str, int] = field(default_factory=dict)  # findings below min_severity

    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    def exit_status(self, warnings_as_errors: bool = False) -> int:
        if any(f.severity == "error" or (warnings_as_errors and f.severity == "warning") for f in self.findings):
            return 1
        return 0

    def summary(self) -> dict:
        out = {"files": len(self.documents), "findings": len(self.findings)}
        for sev in ("error", "warning", "info"):
            out[sev] = sum(f.severity == sev for f in self.findings)
        return out


_INCLUDE_RE = re.compile(r"\\(input|include|subfile|subimport\*?|import\*?)\s*(?:\{([^}]*)\}\s*)?(?:\{([^}]+)\}|(?<=\\input)\s+([^\s{}%\\]+))")


def _strip_comments(src: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", src)


def resolve_include(base_dir: str, target: str, dir_hint: str | None = None) -> str | None:
    target = target.strip().strip('"')
    if not target:
        return None
    cands = []
    for root in ([os.path.join(base_dir, dir_hint)] if dir_hint else []) + [base_dir]:
        p = os.path.join(root, target)
        cands += [p, p + ".tex"]
    for c in cands:
        if os.path.isfile(c) and not c.endswith((".sty", ".cls", ".bib")):
            return c
    return None


class StyleChecker:
    """Configure once, then check files or text."""

    def __init__(self, options: Options | None = None):
        self.options = options or Options()
        o = self.options
        self.messages: list[str] = []
        for p in o.plugins:
            try:
                load_plugin(p)
            except Exception as e:
                self.messages.append(f"cannot load plugin {p}: {e}")
        if o.compat:
            from .rules import BUNDLED_RULES_DIR, default_rule_paths

            if o.override_rules:
                paths = list(o.override_rules)
            else:
                paths = ([str(BUNDLED_RULES_DIR / "en")] if o.default_rules else []) + (default_rule_paths() if o.user_rules else [])
            paths += o.rules
            self.rules: RuleSet = load_rules(override_paths=paths, use_bundled=False, use_user=False) if paths else RuleSet()
        else:
            self.rules = load_rules(override_paths=o.override_rules or None, extra_paths=o.rules,
                                    use_bundled=o.default_rules, use_user=o.user_rules)
        self.messages += self.rules.errors
        self.checks: dict[str, Check] = {cid: cls() for cid, cls in all_checks().items()}

    # -- selection ---------------------------------------------------------
    def _selected(self, ids: set[str], default: bool) -> bool:
        o = self.options
        if o.only:
            return bool(ids & set(o.only)) or (bool(ids & RULE_KINDS) and "rules" in o.only)
        if ids & set(o.disable) or "all" in o.disable and not ids & set(o.enable):
            return False
        if ids & set(o.enable):
            return True
        return default

    def check_enabled(self, check: Check) -> bool:
        if self.options.compat and check.origin != "style-check":
            return False
        return self._selected({check.id, check.category, "origin:" + check.origin}, check.default_enabled)

    def finding_enabled(self, f: Finding) -> bool:
        ids = {f.check, f.category, *f.tags}
        return self._selected(ids, True)

    # -- running -------------------------------------------------------------
    def check_paths(self, paths: list[str]) -> Report:
        sources: list[tuple[str, str]] = []
        report = Report(messages=list(self.messages))
        for p in paths:
            if p == "-":
                sources.append(("<stdin>", sys.stdin.read()))
                continue
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    sources.append((p, f.read()))
            except OSError as e:
                report.messages.append(f"WARNING: Input file {p} does not exist.  skipping." if not os.path.exists(p) else f"{p}: {e}")
        return self.check_sources(sources, report)

    def check_text(self, text: str, path: str = "<text>") -> Report:
        return self.check_sources([(path, text)], Report(messages=list(self.messages)))

    def check_sources(self, sources: list[tuple[str, str]], report: Report | None = None) -> Report:
        report = report or Report(messages=list(self.messages))
        o = self.options
        files: list[tuple[str, str]] = []
        parent: dict[str, str] = {}
        seen: set[str] = set()
        queue = list(sources)
        while queue:
            path, src = queue.pop(0)
            key = os.path.abspath(path) if not path.startswith("<") else path
            if key in seen:
                continue
            seen.add(key)
            files.append((path, src))
            if not o.follow_includes or path.startswith("<"):
                continue
            base = os.path.dirname(os.path.abspath(path))
            for m in _INCLUDE_RE.finditer(_strip_comments(src)):
                target = resolve_include(base, m.group(3) or m.group(4), m.group(2))
                if target and os.path.abspath(target) not in seen:
                    try:
                        with open(target, encoding="utf-8", errors="replace") as f:
                            queue.append((target, f.read()))
                        parent.setdefault(target, path)
                    except OSError:
                        pass
        defs = latexdb.Definitions()
        for _, src in files:
            defs.merge(latexdb.scan_definitions(src))
        defs.ignored_macros |= self.rules.ignored_commands | set(o.ignored_commands)
        defs.ignored_envs |= self.rules.ignored_environments | set(o.ignored_environments)
        docs = [parse(p, s, defs) for p, s in files]
        self._resolve_languages(docs, parent)
        report.documents = docs

        ctx = Context(options=self._ctx_options(), rules=self.rules)
        raw: list[Finding] = []
        for c in self.checks.values():
            if not self.check_enabled(c):
                continue
            try:
                if isinstance(c, ProjectCheck):
                    raw += list(c.check_project([d for d in docs if c.applies_to(d.language)], ctx))
                else:
                    for d in docs:
                        if c.applies_to(d.language) or o.compat:
                            raw += list(c.check(d, ctx))
            except Exception as e:  # a broken check must not hide the others
                report.messages.append(f"check {c.id} failed: {type(e).__name__}: {e}")
        report.findings = self._postprocess(raw, docs)
        report.hidden = dict(self._hidden)
        return report

    def _ctx_options(self) -> dict:
        o = self.options
        return {
            "compat": o.compat,
            "max_sentence_words": o.max_sentence_words,
            "max_significant_digits": o.max_significant_digits,
            "duplicate_allowed": o.duplicate_allowed,
            "acronyms_allowed": o.acronyms_allowed,
            "frenchspacing": o.frenchspacing,
            "is_disabled": lambda ids: not self._selected(set(ids), True),
        }

    def _resolve_languages(self, docs: list[Document], parent: dict[str, str]) -> None:
        o = self.options
        by_path = {d.path: d for d in docs}
        for d in docs:
            if o.language and o.language != "auto":
                d.language = o.language
                continue
            if d.declared_language:
                continue
            p = parent.get(d.path)
            while p is not None:
                pd = by_path.get(p)
                if pd is not None and pd.declared_language:
                    d.language = pd.declared_language
                    break
                p = parent.get(p)

    def _postprocess(self, raw: list[Finding], docs: list[Document]) -> list[Finding]:
        o = self.options
        by_path = {d.path: d for d in docs}
        out: list[Finding] = []
        seen: set[tuple] = set()
        min_rank = SEVERITY_RANK.get(o.min_severity or "info", 2)
        self._hidden: dict[str, int] = {}
        # the most severe finding, then built-in checks, win over duplicates
        raw.sort(key=lambda f: (f.path, f.line, f.column, SEVERITY_RANK.get(f.severity, 2), f.check in RULE_KINDS))
        for f in raw:
            if f.check in o.severity:
                f.severity = o.severity[f.check]
            if not self.finding_enabled(f):
                continue
            d = by_path.get(f.path)
            if d is not None and d.suppressions.suppressed(f.line, {f.check, f.category, *f.tags}):
                continue
            if SEVERITY_RANK.get(f.severity, 2) > min_rank:
                self._hidden[f.severity] = self._hidden.get(f.severity, 0) + 1
                continue
            key = (f.path, f.line, f.column, re.sub(r"\s+", " ", f.matched).strip()) if not o.compat else (f.path, f.start, f.rule_source, f.check)
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        out.sort(key=lambda f: f.sort_key)
        return out


def apply_fixes(report: Report, only: set[str] | None = None) -> dict[str, tuple[str, str]]:
    """Return {path: (old, new)} after applying non-overlapping replacements."""
    by_path: dict[str, list[Finding]] = {}
    for f in report.findings:
        if f.replacement is None or (only and f.check not in only):
            continue
        by_path.setdefault(f.path, []).append(f)
    out = {}
    docs = {d.path: d for d in report.documents}
    for path, fs in by_path.items():
        d = docs.get(path)
        if d is None:
            continue
        src = d.source
        fs.sort(key=lambda f: (f.start, f.end))
        chosen: list[Finding] = []
        last_end = -1
        for f in fs:
            if f.start >= last_end:
                chosen.append(f)
                last_end = max(f.end, f.start + 1)
        new = src
        for f in reversed(chosen):
            new = new[: f.start] + f.replacement + new[f.end :]
        if new != src:
            out[path] = (src, new)
    return out


def unified_diff(changes: dict[str, tuple[str, str]]) -> str:
    parts = []
    for path, (old, new) in changes.items():
        parts += difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=path, tofile=path)
    return "".join(parts)
