"""Check registry and base classes.

Writing a check is the main way to extend pystylecheck::

    from pystylecheck.checks import Check, register

    @register
    class NoTodo(Check):
        id = "no-todo"
        description = "TODO markers left in the text"
        severity = "error"

        def check(self, doc, ctx):
            for b in doc.blocks:
                for m in re.finditer(r"\\bTODO\\b", b.text):
                    yield ctx.at_prose(self, doc, b, m.start(), m.end(),
                                       "remove the TODO marker")

Put the module on the command line (``--plugin mychecks.py``), in the
configuration file (``plugins = ["mychecks"]``), or expose it as a
``pystylecheck.checks`` entry point in a package.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from ..findings import Finding

if TYPE_CHECKING:  # pragma: no cover
    from ..latex import Block, Document

_REGISTRY: dict[str, type["Check"]] = {}


class Check:
    """A check run on each document."""

    id: str = ""
    description: str = ""
    explanation: str = ""  # longer rationale, shown with --explain / -v
    category: str = "style"
    severity: str = "warning"
    languages: frozenset[str] | None = None  # None: every language
    default_enabled: bool = True
    origin: str = "pystylecheck"  # 'style-check', 'guide' or 'pystylecheck'
    fixable: bool = False

    def check(self, doc: "Document", ctx: "Context") -> Iterable[Finding]:
        return ()

    def applies_to(self, lang: str) -> bool:
        return self.languages is None or lang in self.languages


class ProjectCheck(Check):
    """A check that needs all the documents at once (labels, consistency...)."""

    def check_project(self, docs: list["Document"], ctx: "Context") -> Iterable[Finding]:
        return ()


def register(cls: type[Check]) -> type[Check]:
    """Class decorator registering a check."""
    if not cls.id:
        raise ValueError(f"{cls.__name__} has no id")
    _REGISTRY[cls.id] = cls
    return cls


def all_checks() -> dict[str, type[Check]]:
    _load_builtin()
    return dict(_REGISTRY)


_builtin_loaded = False


def _load_builtin() -> None:
    global _builtin_loaded
    if _builtin_loaded:
        return
    _builtin_loaded = True
    from . import stylecheck, prose, structure, references, floats, mathcheck, typography, consistency, lacheck  # noqa: F401

    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group="pystylecheck.checks"):
            try:
                ep.load()
            except Exception as e:  # pragma: no cover
                print(f"pystylecheck: cannot load plugin {ep.name}: {e}", file=sys.stderr)
    except Exception:  # pragma: no cover
        pass


def load_plugin(spec: str) -> None:
    """Import a plugin given as a module name or a path to a .py file."""
    _load_builtin()
    if spec.endswith(".py"):
        name = "pystylecheck_plugin_" + str(abs(hash(spec)))
        s = importlib.util.spec_from_file_location(name, spec)
        if s is None or s.loader is None:
            raise ImportError(f"cannot load plugin {spec}")
        mod = importlib.util.module_from_spec(s)
        sys.modules[name] = mod
        s.loader.exec_module(mod)
    else:
        importlib.import_module(spec)


@dataclass
class Context:
    """What checks know about the run: options and helpers to make findings."""

    options: dict = field(default_factory=dict)
    rules: object = None  # RuleSet

    def opt(self, name: str, default=None):
        return self.options.get(name, default)

    def make(
        self,
        check: Check,
        doc: "Document",
        start: int,
        end: int,
        message: str,
        *,
        severity: str | None = None,
        replacement: str | None = None,
        check_id: str | None = None,
        explanation: str | None = None,
        category: str | None = None,
        rule_source: str | None = None,
        matched: str | None = None,
    ) -> Finding:
        end = max(end, start)
        line, col = doc.line_col(start)
        eline, ecol = doc.line_col(end)
        return Finding(
            check=check_id or check.id,
            message=message,
            severity=severity or check.severity,
            path=doc.path,
            start=start,
            end=end,
            line=line,
            column=col,
            end_line=eline,
            end_column=ecol,
            matched=matched if matched is not None else doc.source[start:end],
            excerpt=doc.line_text(line),
            category=category or check.category,
            explanation=explanation if explanation is not None else check.explanation,
            rule_source=rule_source,
            replacement=replacement,
        )

    def at_prose(self, check: Check, doc: "Document", block: "Block", i: int, j: int, message: str, **kw) -> Finding:
        s, e = block.span(i, j)
        if "matched" not in kw:
            kw["matched"] = doc.source[s:e]
        return self.make(check, doc, s, e, message, **kw)


__all__ = ["Check", "ProjectCheck", "Context", "register", "all_checks", "load_plugin"]
