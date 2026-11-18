#!/usr/bin/env python3
"""Refresh the bundled avoid-ai-writing patterns.

pystylecheck's ``ai-*`` checks read ``src/pystylecheck/data/avoid_ai_writing.json``,
which this script generates from https://github.com/conorbronsdon/avoid-ai-writing:

* the pattern tables come from the ``PATTERN_TABLES`` export of
  ``detector/patterns.js`` (the data the upstream detector and its Vale style use);
* the severity of each type comes from the level of the matching rule in the
  generated Vale style (``vale/AvoidAIWriting``): error, warning or suggestion (info);
* the terms exempt in technical writing come from ``TECHNICAL_EXEMPT``.

Usage::

    python scripts/sync_avoid_ai_writing.py              # latest main
    python scripts/sync_avoid_ai_writing.py --ref v3.39.0
    python scripts/sync_avoid_ai_writing.py --from ../avoid-ai-writing   # a local clone

It needs git and Node.js (18 or later). Run ``uv run pytest`` afterwards: the tests
fail when upstream adds or changes a gate (a rule that needs more than a regex)
that pystylecheck does not implement yet.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "https://github.com/conorbronsdon/avoid-ai-writing"
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "src" / "pystylecheck" / "data"
OUT = DATA_DIR / "avoid_ai_writing.json"
LICENSE_OUT = DATA_DIR / "avoid_ai_writing.LICENSE"

LEVELS = {"error": "error", "warning": "warning", "suggestion": "info"}
RANK = {"error": 0, "warning": 1, "info": 2}

DUMP_JS = """
const p = require(process.argv[1]);
process.stdout.write(JSON.stringify({
  tables: p.PATTERN_TABLES,
  labels: p.TYPE_LABELS,
}));
"""


def run(cmd: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def technical_exempt(source: str) -> list[str]:
    m = re.search(r"const\s+TECHNICAL_EXEMPT\s*=\s*new\s+Set\(\s*\[(.*?)\]\s*\)", source, re.S)
    if not m:
        sys.exit("cannot find TECHNICAL_EXEMPT in detector/patterns.js: update this script")
    return [a or b for a, b in re.findall(r"'([^']*)'|\"([^\"]*)\"", m.group(1))]


def vale_level(style: Path, rule: str) -> str | None:
    """Level of a Vale rule such as 'AvoidAIWriting.Fillers' or 'AvoidAIWriting.overuse.*'."""
    parts = rule.split(".")[1:]
    files = sorted(style.glob("/".join(parts[:-1] + ["*.yml"]))) if parts[-1] == "*" else [style.joinpath(*parts[:-1], parts[-1] + ".yml")]
    best = None
    for f in files:
        if not f.is_file():
            continue
        m = re.search(r"^level:\s*(\w+)", f.read_text(encoding="utf-8"), re.M)
        if m and m.group(1) in LEVELS:
            lvl = LEVELS[m.group(1)]
            if best is None or RANK[lvl] < RANK[best]:
                best = lvl
    return best


def build(repo: Path) -> dict:
    patterns_js = repo / "detector" / "patterns.js"
    dumped = json.loads(run(["node", "-e", DUMP_JS, str(patterns_js)]))
    tables, labels = dumped["tables"], dumped["labels"]
    style = repo / "vale" / "AvoidAIWriting"
    manifest = json.loads((style / "manifest.json").read_text(encoding="utf-8"))
    status = {t["type"]: t for t in manifest["types"]}
    package = json.loads((repo / "package.json").read_text(encoding="utf-8"))

    types = {}
    for name, table in tables["types"].items():
        entry = {"label": labels.get(name, name)}
        levels = [lvl for r in status.get(name, {}).get("rules", []) if (lvl := vale_level(style, r))]
        entry["severity"] = min(levels, key=RANK.get) if levels else None
        entry.update(table)
        types[name] = entry

    def git(*args: str) -> str:
        try:
            return run(["git", *args], cwd=repo).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    return {
        "source": {
            "repository": REPO,
            "version": package.get("version", ""),
            "commit": git("rev-parse", "HEAD"),
            "date": git("log", "-1", "--format=%cs"),
            "license": package.get("license", ""),
            "patterns_sha256": manifest.get("source", {}).get("sha256", ""),
        },
        "schema_version": tables.get("schemaVersion", ""),
        "technical_exempt": technical_exempt(patterns_js.read_text(encoding="utf-8")),
        "types": types,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="main", help="branch, tag or commit to fetch (default: main)")
    ap.add_argument("--from", dest="local", metavar="PATH", help="use a local clone instead of fetching")
    ap.add_argument("--check", action="store_true", help="exit 1 if the bundled data is out of date; write nothing")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        if args.local:
            repo = Path(args.local).resolve()
        else:
            repo = Path(tmp) / "avoid-ai-writing"
            run(["git", "init", "-q", str(repo)])
            run(["git", "fetch", "-q", "--depth", "1", REPO, args.ref], cwd=repo)
            run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=repo)
        data = build(repo)
        text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        # the commit changes on every upstream push; only the data matters for --check
        changed = json.loads(old or "{}").get("types") != data["types"] or json.loads(old or "{}").get("technical_exempt") != data["technical_exempt"]
        src = data["source"]
        print(f"avoid-ai-writing {src['version']} ({src['commit'][:12]}, {src['date']}): "
              f"{len(data['types'])} types, " + ("patterns changed" if changed else "patterns unchanged"))
        if args.check:
            return 1 if changed else 0
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        shutil.copyfile(repo / "LICENSE", LICENSE_OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
