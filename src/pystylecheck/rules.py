"""Rule files in the style-check.rb format.

Each non-empty line of a rule file is::

    <regular expression>   % <kind> <explanation>

where ``kind`` is one of:

``syntax``
    case-sensitive regular expression, matched as is against the LaTeX
    source (comments removed; math, verbatim and ignored command
    arguments masked).
``capitalize``
    case-sensitive, wrapped in ``\\b`` so that only whole words match.
``phrase``
    case-insensitive, wrapped in ``\\b``; spaces match any whitespace.
``spelling``
    case-insensitive, wrapped in ``\\b``.
``ignoredcommand``
    the expression is a macro name whose arguments are ignored.

pystylecheck adds two kinds:

``prose``
    case-sensitive regular expression matched against the prose (markup
    removed, so it sees ``\\emph{very} unique`` as ``very unique``).
``ignoredenvironment``
    the expression is an environment whose body is not prose.

An explanation ending with ``?`` marks a weak rule: it is reported as a
warning and does not change the exit status.  A second word ``ignore``
(``% phrase ignore``) disables the rule, as in style-check.rb.  Lines
starting with ``#`` are comments.  A comment ``# pystylecheck: lang=fr``
restricts a whole file to documents in that language.

Phrase, spelling and capitalize rules are matched against the prose, so
they work across line breaks, inside ``\\emph{}`` and never inside math,
code, URLs or citation keys.  When such a rule mentions LaTeX itself (a
backslash, ``~``, a brace or ``$``), it is matched against the source
instead.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

RULE_KINDS = ("syntax", "capitalize", "phrase", "spelling", "prose")
_LATEX_IN_PATTERN = re.compile(r"\\\\|~|\\\{|\\\}|\\\$")

BUNDLED_RULES_DIR = Path(__file__).parent / "rules"


@dataclass
class Rule:
    expression: str
    kind: str
    reason: str
    regex: re.Pattern
    target: str  # 'source' or 'prose'
    file: str
    line: int
    language: str | None = None

    @property
    def weak(self) -> bool:
        return self.reason.rstrip().endswith("?")

    @property
    def explanation(self) -> str:
        r = self.reason.split(None, 1)
        return r[1].strip() if len(r) > 1 else ""

    @property
    def source_ref(self) -> str:
        return f"{self.file}:{self.line}"

    @property
    def file_stem(self) -> str:
        return os.path.basename(self.file)


@dataclass
class RuleSet:
    rules: list[Rule] = field(default_factory=list)
    ignored_commands: set[str] = field(default_factory=set)
    ignored_environments: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def for_language(self, lang: str) -> list[Rule]:
        return [r for r in self.rules if r.language is None or r.language == lang]


def _ruby_to_python(expr: str) -> str:
    """Translate the few Ruby-only regex constructs to Python."""
    return expr.replace(r"\z", r"\Z").replace(r"\h", r"[0-9a-fA-F]")


def compile_rule(expression: str, kind: str) -> tuple[re.Pattern, str]:
    """Compile an expression the way style-check.rb does; return (regex, target)."""
    expr = _ruby_to_python(expression)
    flags = re.MULTILINE  # in Ruby, ^ and $ always match at line breaks
    if kind == "syntax":
        pattern = expr
    elif kind == "prose":
        pattern = expr
    elif kind == "capitalize":
        pattern = r"\b" + expr + r"\b"
    elif kind == "phrase":
        pattern = r"\b" + re.sub(r"([a-zA-Z\)])$", r"\1\\b", re.sub(r" +", r"\\s+", expr))
        flags |= re.IGNORECASE
    elif kind == "spelling":
        pattern = r"\b" + expr + r"\b"
        flags |= re.IGNORECASE
    else:  # unknown class: style-check warns and treats it as capitalize
        pattern = r"\b" + expr + r"\b"
    if kind == "syntax":
        target = "source"
    elif kind == "prose":
        target = "prose"
    else:
        target = "source" if _LATEX_IN_PATTERN.search(expression) else "prose"
    return re.compile(pattern, flags), target


def _file_language(path: str, lines: list[str]) -> str | None:
    for ln in lines[:10]:
        m = re.match(r"\s*#\s*pystylecheck:\s*lang(?:uage)?\s*=\s*(\w+)", ln)
        if m:
            return m.group(1).lower()
    parent = os.path.basename(os.path.dirname(path))
    if parent in ("en", "fr"):
        return parent
    return None


def load_rule_file(path: str, ruleset: RuleSet, display_name: str | None = None) -> None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as e:
        ruleset.errors.append(f"{path}: {e}")
        return
    name = display_name or path
    ruleset.files.append(name)
    lang = _file_language(path, lines)
    for i, ln in enumerate(lines, 1):
        if ln.lstrip().startswith("#") or not ln.strip():
            continue
        parts = re.split(r"\s*%\s*", ln, maxsplit=1)
        if len(parts) < 2:
            continue
        expression, reason = parts
        if not expression:
            continue
        words = reason.split()
        kind = words[0] if words else ""
        if len(words) > 1 and "ignore" in words[1]:
            continue
        if kind == "ignoredcommand":
            ruleset.ignored_commands.add(expression.strip().lstrip("\\"))
            continue
        if kind == "ignoredenvironment":
            ruleset.ignored_environments.add(expression.strip())
            continue
        if kind not in RULE_KINDS:
            ruleset.errors.append(f"warning: no class specified for {expression} at {name}:{i}")
        try:
            regex, target = compile_rule(expression, kind)
        except re.error as e:
            ruleset.errors.append(f"{name}:{i}: Error: {e}")
            continue
        ruleset.rules.append(Rule(expression, kind if kind in RULE_KINDS else "capitalize", reason, regex, target, name, i, lang))


def default_rule_paths() -> list[str]:
    """Rule locations searched by style-check.rb, plus pystylecheck's own."""
    home = Path.home()
    paths: list[str] = []
    for d in ("/etc/style-check.d", str(home / ".style-check.d"), str(_config_home() / "rules")):
        if os.path.isdir(d):
            paths += sorted(os.path.join(d, f) for f in os.listdir(d))
    paths += [str(home / ".style-censor"), "./censor-dict", "/etc/style-censor", "./style-censor"]
    return [p for p in paths if os.path.isfile(p) and not p.endswith("~")]


def _config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "pystylecheck"


def bundled_rule_files() -> list[str]:
    out = []
    for sub in sorted(BUNDLED_RULES_DIR.iterdir()):
        if sub.is_dir():
            out += sorted(str(p) for p in sub.iterdir() if p.is_file())
    return out


def expand_rule_path(p: str) -> list[str]:
    if os.path.isdir(p):
        return sorted(os.path.join(p, f) for f in os.listdir(p) if os.path.isfile(os.path.join(p, f)) and not f.endswith("~"))
    return [p]


def load_rules(
    override_paths: list[str] | None = None,
    extra_paths: list[str] | None = None,
    use_bundled: bool = True,
    use_user: bool = True,
) -> RuleSet:
    """Load rules: bundled + style-check locations (or the override) + extras."""
    rs = RuleSet()
    seen: set[tuple[str, str]] = set()
    files: list[tuple[str, str]] = []
    if override_paths:
        for p in override_paths:
            files += [(f, f) for f in expand_rule_path(p)]
    else:
        if use_bundled:
            files += [(f, "rules/" + os.path.relpath(f, BUNDLED_RULES_DIR)) for f in bundled_rule_files()]
        if use_user:
            files += [(f, f) for f in default_rule_paths()]
    for p in extra_paths or []:
        files += [(f, f) for f in expand_rule_path(p)]
    for path, name in files:
        before = len(rs.rules)
        load_rule_file(path, rs, name)
        # the same rule installed twice (bundled and ~/.style-check.d) is reported once
        kept = []
        for r in rs.rules[before:]:
            key = (r.expression, r.kind)
            if key in seen:
                continue
            seen.add(key)
            kept.append(r)
        rs.rules[before:] = kept
    return rs
