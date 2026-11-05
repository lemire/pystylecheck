"""Consistency of spelling across the whole project."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from . import ProjectCheck, register

_TOKEN = re.compile(r"(?<![\w.-])([^\W_][\w]*(?:[-.][\w]+)*)(?![\w-])")


def _canonical(w: str) -> str:
    """Lowercase the first letter unless the word has other capitals."""
    if w[1:] == w[1:].lower():
        return w[0].lower() + w[1:]
    return w


def _case_only(a: str, b: str) -> bool:
    return a.lower() == b.lower()


@register
class InconsistentSpelling(ProjectCheck):
    id = "inconsistent-spelling"
    description = "The same term written in different ways (Bozo3 / BOZO-3, e-mail / email)"
    explanation = (
        "Be consistent from start to finish: if you write Bozo3 in the introduction, do not write "
        "BOZO-3 in the conclusion. Is it .net or .NET? Choose and apply the choice everywhere. "
        "Title-case headings and words in capitals for emphasis are not counted as variants."
    )
    category = "consistency"
    severity = "warning"
    origin = "guide"

    def check_project(self, docs, ctx):
        groups: dict[str, Counter] = defaultdict(Counter)
        first: dict[str, tuple] = {}
        surface: dict[str, Counter] = defaultdict(Counter)
        for d in docs:
            for b in d.prose_blocks("paragraph", "item", "footnote", "caption", "heading", "title", "cell"):
                titleish = b.kind in ("heading", "title")
                for m in _TOKEN.finditer(b.text):
                    w = m.group(1)
                    if len(w) < 3 or w.isdigit() or not any(c.isalpha() for c in w):
                        continue
                    key = re.sub(r"[-.]", "", w.lower())
                    c = _canonical(w)
                    if titleish:
                        # In a Title-Case heading, "Compile-Time" says nothing about spelling
                        # unless the form differs by more than case.
                        c = ("~title", c)
                    groups[key][c] += 1
                    surface[str(c)][w] += 1
                    first.setdefault(c, (d, b, m.start(1), m.end(1)))
        for key, forms in groups.items():
            body_forms = Counter({f: n for f, n in forms.items() if not isinstance(f, tuple)})
            title_forms = [f[1] for f in forms if isinstance(f, tuple)]
            # title forms matter only when they differ from every body form by more than case
            seen_names = [f for f in body_forms]
            for t in title_forms:
                if not any(_case_only(t, f) for f in seen_names):
                    body_forms[("~title", t)] = forms[("~title", t)]
                    seen_names.append(t)
            if len(body_forms) < 2:
                continue
            names = [f[1] if isinstance(f, tuple) else f for f in body_forms]
            if not any(re.search(r"[-.\d]|.[A-Z]", f) for f in names):
                continue
            ranked = body_forms.most_common()
            main, n_main = ranked[0]
            main_name = main[1] if isinstance(main, tuple) else main
            main_shown = surface[str(main)].most_common(1)[0][0]
            for form, n in ranked[1:]:
                name = form[1] if isinstance(form, tuple) else form
                if _case_only(name, main_name) and (name.isupper() or main_name.isupper()) and "-" not in name + main_name:
                    continue  # "ALL" for emphasis, "NUMA"/"numa"...
                d, b, i, j = first[form]
                shown = surface[str(form)].most_common(1)[0][0]
                yield ctx.at_prose(self, d, b, i, j,
                                   f"'{shown}' ({n}x) is also written '{main_shown}' ({n_main}x): choose one spelling")
