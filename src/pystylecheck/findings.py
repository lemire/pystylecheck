"""Findings reported by checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SEVERITIES = ("error", "warning", "info")
SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Finding:
    """One problem found in a document.

    ``start``/``end`` are offsets in the source; ``line``/``column`` are
    1-based.  ``replacement``, when set, is a safe fix: replacing
    ``source[start:end]`` with it resolves the finding.
    """

    check: str
    message: str
    severity: str
    path: str
    start: int
    end: int
    line: int = 0
    column: int = 0
    end_line: int = 0
    end_column: int = 0
    matched: str = ""
    excerpt: str = ""
    category: str = ""
    explanation: str = ""
    rule_source: str | None = None
    replacement: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["replacement"] is None:
            del d["replacement"]
        if d["rule_source"] is None:
            del d["rule_source"]
        if not d["tags"]:
            del d["tags"]
        return d

    @property
    def sort_key(self):
        return (self.path, self.line, self.column, SEVERITY_RANK.get(self.severity, 9), self.check)
