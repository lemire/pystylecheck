"""Checks on figures, tables and graphics."""

from __future__ import annotations

import os
import re

from ..latexdb import FLOAT_ENVS, TABULAR_ENVS
from . import Check, register

_BITMAP = {".png", ".gif", ".bmp", ".tif", ".tiff", ".jpg", ".jpeg", ".webp"}
_VECTOR = {".pdf", ".eps", ".ps", ".svg", ".pgf", ".tikz", ".mps"}


@register
class FloatPlacement(Check):
    id = "float-placement"
    description = "Let LaTeX place floats: avoid [h], [H] and [h!]"
    explanation = (
        "Figures and tables float: they belong at the top or bottom of a page, not in the middle of "
        "the text. Forcing [h] or [H] gives ugly pages; prefer [tbp] or no option."
    )
    category = "float"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        for f in doc.floats:
            p = (f.placement or "").replace("!", "")
            if f.placement is not None and p in ("h", "H") and f.env not in ("wrapfigure", "wraptable"):
                yield ctx.make(self, doc, f.placement_pos, f.placement_pos + len(f.placement) + 2,
                               f"[{f.placement}] forces the float in the middle of the text: let LaTeX place it ([tbp])")


@register
class CaptionPosition(Check):
    id = "caption-position"
    description = "Figure captions go below the figure, table captions above the table"
    category = "float"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        for f in doc.floats:
            if not f.captions or not f.content_positions:
                continue
            cap = f.caption_positions[0]
            first, last = min(f.content_positions), max(f.content_positions)
            if "table" in f.env and f.tabulars and cap > last:
                yield ctx.make(self, doc, cap, cap + 8, "a table caption goes above the table")
            elif "figure" in f.env and not f.tabulars and cap < first:
                yield ctx.make(self, doc, cap, cap + 8, "a figure caption goes below the figure")


@register
class TableRules(Check):
    id = "table-rules"
    description = "Tables: no vertical lines; use booktabs (\\toprule, \\midrule, \\bottomrule) instead of \\hline"
    explanation = (
        "In a table, avoid vertical lines; three horizontal lines usually suffice: at the top, after "
        "the column titles and at the bottom. LaTeX users should use the booktabs package."
    )
    category = "float"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        for t in doc.tabulars:
            if t.colspec and "|" in t.colspec and t.colspec_pos is not None:
                yield ctx.make(self, doc, t.colspec_pos, t.colspec_pos + len(t.colspec) + 2,
                               "avoid vertical lines in tables")
            if t.hlines:
                p, e = t.hlines[0]
                n = len(t.hlines)
                yield ctx.make(self, doc, p, e, f"use booktabs (\\toprule, \\midrule, \\bottomrule) rather than \\hline ({n} in this table)")


@register
class BitmapFigure(Check):
    id = "bitmap-figure"
    description = "Figures should be vector graphics (PDF, SVG, TikZ), not bitmaps (PNG, JPEG)"
    explanation = (
        "Scientific figures use a vector format. Bitmaps blur when zoomed. JPEG is acceptable for "
        "photographs, and screenshots may be bitmaps; plots, diagrams and tables should not be."
    )
    category = "float"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        base = os.path.dirname(os.path.abspath(doc.path)) if doc.path and not doc.path.startswith("<") else None
        for path, pos, end in doc.graphics:
            ext = os.path.splitext(path)[1].lower()
            if not ext and base:
                for cand in (".pdf", ".eps", ".svg", ".png", ".jpg", ".jpeg"):
                    if os.path.exists(os.path.join(base, path + cand)):
                        ext = cand
                        break
            if ext in _BITMAP:
                kind = "photograph" if ext in (".jpg", ".jpeg") else "bitmap"
                hint = " (fine for a photograph)" if kind == "photograph" else ""
                yield ctx.make(self, doc, pos, end, f"'{path}' is a bitmap image{hint}: prefer a vector format (PDF, SVG or TikZ)",
                               severity="info" if kind == "photograph" else None)


@register
class FramedFloat(Check):
    id = "framed-float"
    description = "Do not put figures and tables in a box"
    category = "float"
    severity = "warning"
    origin = "guide"

    def check(self, doc, ctx):
        for f in doc.floats:
            if f.has_frame:
                yield ctx.make(self, doc, f.pos, f.pos + len(f.env) + 8, "do not frame figures and tables (\\fbox)")
