"""Configuration: TOML files and style-check.rb's ~/.style-checkrc."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

CONFIG_NAMES = (".pystylecheck.toml", "pystylecheck.toml")


@dataclass
class Options:
    language: str = "auto"  # auto, en, fr
    enable: list[str] = field(default_factory=list)
    disable: list[str] = field(default_factory=list)
    only: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)  # extra rule files or directories
    override_rules: list[str] = field(default_factory=list)  # style-check -r
    default_rules: bool = True  # bundled rules
    user_rules: bool = True  # ~/.style-check.d and friends
    plugins: list[str] = field(default_factory=list)
    ignored_commands: list[str] = field(default_factory=list)
    ignored_environments: list[str] = field(default_factory=list)
    max_sentence_words: int = 30
    max_significant_digits: int = 3
    duplicate_allowed: list[str] = field(default_factory=list)
    acronyms_allowed: list[str] = field(default_factory=list)
    min_severity: str | None = None  # None: "warning" for text output, "info" otherwise
    follow_includes: bool = True
    warnings_as_errors: bool = False
    severity: dict[str, str] = field(default_factory=dict)
    frenchspacing: bool = False
    compat: bool = False  # behave like style-check.rb: its rules and built-ins only

    def update(self, data: dict, source: str = "") -> list[str]:
        """Merge a mapping (from TOML); return warnings for unknown keys."""
        known = {f.name: f for f in fields(self)}
        warnings = []
        for k, v in data.items():
            key = k.replace("-", "_")
            if key not in known:
                warnings.append(f"{source}: unknown option '{k}'")
                continue
            cur = getattr(self, key)
            if isinstance(cur, list) and isinstance(v, list):
                setattr(self, key, cur + [str(x) for x in v] if key in ("enable", "disable", "rules", "plugins", "ignored_commands", "ignored_environments", "duplicate_allowed", "acronyms_allowed") else [str(x) for x in v])
            elif isinstance(cur, dict) and isinstance(v, dict):
                cur.update({str(a): str(b) for a, b in v.items()})
            else:
                setattr(self, key, v)
        return warnings


def config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "pystylecheck"


def find_project_config(start: str) -> Path | None:
    p = Path(start).resolve()
    if p.is_file():
        p = p.parent
    for d in [p, *p.parents]:
        for name in CONFIG_NAMES:
            c = d / name
            if c.is_file():
                return c
        pp = d / "pyproject.toml"
        if pp.is_file():
            try:
                if "pystylecheck" in tomllib.loads(pp.read_text(encoding="utf-8")).get("tool", {}):
                    return pp
            except (OSError, tomllib.TOMLDecodeError):
                pass
    return None


def load_toml(path: Path) -> dict:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if path.name == "pyproject.toml":
        return data.get("tool", {}).get("pystylecheck", {})
    return data.get("pystylecheck", data)


def read_style_checkrc() -> dict:
    """Options from style-check.rb's ~/.style-checkrc (key or key=value lines)."""
    rc = Path.home() / ".style-checkrc"
    out: dict = {}
    if not rc.is_file():
        return out
    for ln in rc.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        k, _, v = ln.partition("=")
        out[k.strip()] = v.strip() if v else True
    return out


def load_options(start: str | None = None, explicit: str | None = None) -> tuple[Options, list[str]]:
    """Defaults <- user config <- project config (or the explicit file)."""
    opts = Options()
    warnings: list[str] = []
    user = config_home() / "config.toml"
    files = []
    if user.is_file():
        files.append(user)
    if explicit:
        files.append(Path(explicit))
    else:
        proj = find_project_config(start or os.getcwd())
        if proj:
            files.append(proj)
    for f in files:
        try:
            warnings += opts.update(load_toml(f), str(f))
        except (OSError, tomllib.TOMLDecodeError) as e:
            warnings.append(f"{f}: {e}")
    return opts, warnings
