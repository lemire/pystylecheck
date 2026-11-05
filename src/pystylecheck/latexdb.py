"""Knowledge about LaTeX macros and environments.

This module tells the parser how many arguments common macros take and what
each macro *means* for prose: is its argument text (``\\emph``), a
reference (``\\ref``), code (``\\texttt``), or something to skip entirely
(``\\label``)?  It also scans a document for user definitions such as
``\\newcommand`` or ``\\newtcblisting`` so that user macros and code
environments are understood too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Placeholders inserted in the prose for things that are not words.
# They come from the Unicode private use area: they are neither word
# characters nor whitespace, so regular expressions treat them as
# punctuation-like separators.
PH_MATH = "\ue000"  # inline math
PH_DISPLAY = "\ue001"  # display math
PH_REF = "\ue002"  # \ref and friends
PH_CITE = "\ue003"  # \cite and friends
PH_CODE = "\ue004"  # \verb, \texttt, \url...
PH_OTHER = "\ue005"  # anything else that renders to something unknown
PH_SEP = "\ue006"  # table cell separator
PH_UNIT = "\ue007"  # siunitx unit

PLACEHOLDERS = frozenset(
    [PH_MATH, PH_DISPLAY, PH_REF, PH_CITE, PH_CODE, PH_OTHER, PH_SEP, PH_UNIT]
)
PLACEHOLDER_CLASS = "[" + "".join(sorted(PLACEHOLDERS)) + "]"

PLACEHOLDER_NAMES = {
    PH_MATH: "math",
    PH_DISPLAY: "display math",
    PH_REF: "reference",
    PH_CITE: "citation",
    PH_CODE: "code",
    PH_OTHER: "command",
    PH_SEP: "cell separator",
    PH_UNIT: "unit",
}

SECTION_LEVELS = {
    "part": -1,
    "chapter": 0,
    "addchap": 0,
    "section": 1,
    "addsec": 1,
    "subsection": 2,
    "subsubsection": 3,
    "paragraph": 4,
    "subparagraph": 5,
}

# Macro name -> index of the argument that holds prose (-1: last argument).
TEXT_ARG_MACROS = {
    "emph": -1,
    "textit": -1,
    "textbf": -1,
    "textsl": -1,
    "textsc": -1,
    "textup": -1,
    "textmd": -1,
    "textrm": -1,
    "textsf": -1,
    "textnormal": -1,
    "underline": -1,
    "uline": -1,
    "uwave": -1,
    "sout": -1,
    "hl": -1,
    "mbox": -1,
    "makebox": -1,
    "fbox": -1,
    "framebox": -1,
    "parbox": -1,
    "raisebox": -1,
    "text": -1,
    "textsuperscript": -1,
    "textsubscript": -1,
    "foreignlanguage": -1,
    "textcolor": -1,
    "colorbox": -1,
    "fcolorbox": -1,
    "href": -1,
    "hyperref": -1,
    "hyperlink": -1,
    "hypertarget": -1,
    "multicolumn": -1,
    "multirow": -1,
    "enquote": -1,
    "textquote": -1,
    "foreignquote": -1,
    "hspace": None,  # handled as space
}

QUOTE_MACROS = frozenset(["enquote", "textquote", "foreignquote"])

FOOTNOTE_MACROS = frozenset(
    ["footnote", "footnotetext", "marginpar", "sidenote", "marginnote", "thanks"]
)
CAPTION_MACROS = frozenset(["caption", "captionof", "subcaption", "sidecaption"])
TITLE_MACROS = frozenset(["title", "subtitle"])

REF_MACROS = frozenset(
    [
        "ref",
        "eqref",
        "pageref",
        "autoref",
        "Autoref",
        "cref",
        "Cref",
        "cpageref",
        "Cpageref",
        "vref",
        "Vref",
        "nameref",
        "subref",
        "labelcref",
        "crefrange",
        "Crefrange",
        "autopageref",
        "fref",
        "Fref",
    ]
)
CITE_MACROS = frozenset(
    [
        "cite",
        "citep",
        "citet",
        "citealt",
        "citealp",
        "citeauthor",
        "citeyear",
        "citeyearpar",
        "citenum",
        "parencite",
        "Parencite",
        "textcite",
        "Textcite",
        "autocite",
        "Autocite",
        "footcite",
        "fullcite",
        "smartcite",
        "supercite",
        "Cite",
        "Citet",
        "Citep",
        "citetitle",
    ]
)
CODE_MACROS = frozenset(
    ["verb", "lstinline", "mintinline", "texttt", "path", "url", "nolinkurl", "code", "Verb"]
)
URL_MACROS = frozenset(["url", "nolinkurl", "href"])
INCLUDE_MACROS = frozenset(["input", "include", "subfile", "import", "subimport", "includefrom"])
BOLD_MACROS = frozenset(["textbf", "bfseries", "bf", "boldmath"])
COLOR_MACROS = frozenset(["textcolor", "color", "colorbox", "fcolorbox"])

# Macros that render to nothing (or to a space) and whose arguments are not prose.
SKIP_MACROS = frozenset(
    [
        "label",
        "index",
        "glossary",
        "nocite",
        "vspace",
        "addvspace",
        "setlength",
        "addtolength",
        "settowidth",
        "setcounter",
        "addtocounter",
        "stepcounter",
        "refstepcounter",
        "newcommand",
        "renewcommand",
        "providecommand",
        "DeclareRobustCommand",
        "DeclareMathOperator",
        "newenvironment",
        "renewenvironment",
        "newtheorem",
        "theoremstyle",
        "newcounter",
        "usepackage",
        "RequirePackage",
        "documentclass",
        "bibliography",
        "bibliographystyle",
        "addbibresource",
        "printbibliography",
        "hypersetup",
        "sisetup",
        "graphicspath",
        "pagestyle",
        "thispagestyle",
        "pagenumbering",
        "linespread",
        "definecolor",
        "colorlet",
        "selectlanguage",
        "input",
        "include",
        "subfile",
        "import",
        "subimport",
        "includeonly",
        "titleformat",
        "titlespacing",
        "tikzset",
        "usetikzlibrary",
        "pgfplotsset",
        "newtcblisting",
        "newtcolorbox",
        "tcbuselibrary",
        "newmdenv",
        "addto",
        "DeclareSIUnit",
        "author",
        "date",
        "affil",
        "affiliation",
        "institute",
        "email",
        "keywords",
        "addcontentsline",
        "markboth",
        "markright",
        "lstset",
        "lstnewenvironment",
        "newminted",
        "setminted",
        "DefineVerbatimEnvironment",
        "crefname",
        "Crefname",
        "newacronym",
        "newglossaryentry",
        "geometry",
        "setmainfont",
        "setsansfont",
        "setmonofont",
        "setmainlanguage",
        "setdefaultlanguage",
        "setotherlanguage",
        "setotherlanguages",
        "AtBeginDocument",
        "makeatletter",
        "makeatother",
        "pgfmathsetmacro",
        "let",
        "def",
        "edef",
        "gdef",
        "xdef",
        "newif",
        "renewrobustcmd",
        "providerobustcmd",
        "phantomsection",
        "cmidrule",
        "cline",
        "hline",
        "toprule",
        "midrule",
        "bottomrule",
        "addlinespace",
        "specialrule",
        "includegraphics",
        "includesvg",
        "includepdf",
        "captionsetup",
        "subcaptionbox",
        "footnotemark",
        "listoffigures",
        "listoftables",
        "tableofcontents",
        "maketitle",
        "today",
        "setcitestyle",
    ]
)

# Macros that render to nothing at all (not even a placeholder).
EMPTY_MACROS = frozenset(
    [
        "-",
        "/",
        "@",
        "xspace",
        "relax",
        "protect",
        "nobreak",
        "allowbreak",
        "unskip",
        "ignorespaces",
        "centering",
        "raggedright",
        "raggedleft",
        "noindent",
        "indent",
        "smallskip",
        "medskip",
        "bigskip",
        "vfill",
        "vfil",
        "clearpage",
        "newpage",
        "cleardoublepage",
        "pagebreak",
        "nopagebreak",
        "appendix",
        "frontmatter",
        "mainmatter",
        "backmatter",
        "tiny",
        "scriptsize",
        "footnotesize",
        "small",
        "normalsize",
        "large",
        "Large",
        "LARGE",
        "huge",
        "Huge",
        "rmfamily",
        "sffamily",
        "ttfamily",
        "mdseries",
        "bfseries",
        "upshape",
        "itshape",
        "slshape",
        "scshape",
        "normalfont",
        "em",
        "it",
        "bf",
        "sl",
        "sc",
        "tt",
        "rm",
        "sf",
        "boldmath",
        "unboldmath",
        "selectfont",
        "frenchspacing",
        "nonfrenchspacing",
        "arraybackslash",
        "strut",
        "null",
        "leavevmode",
        "displaystyle",
        "textstyle",
        "fi",
        "else",
        "color",
        "sloppy",
        "fussy",
        "and",
        "endinput",
        "balance",
        "FloatBarrier",
        "hbox",
        "vbox",
        "begingroup",
        "endgroup",
        "bgroup",
        "egroup",
    ]
)

SPACE_MACROS = {
    " ": " ",
    ",": "\u202f",
    ";": " ",
    ":": " ",
    "!": "",
    "quad": " ",
    "qquad": " ",
    "enspace": " ",
    "enskip": " ",
    "thinspace": "\u202f",
    "space": " ",
    "\\": " ",
    "newline": " ",
    "linebreak": " ",
    "hfill": " ",
    "hfil": " ",
    "hspace": " ",
    "nobreakspace": "\u00a0",
    "nolinebreak": "",
    "break": " ",
}

SYMBOL_MACROS = {
    "S": "§",
    "P": "¶",
    "ldots": "…",
    "dots": "…",
    "textellipsis": "…",
    "LaTeX": "LaTeX",
    "LaTeXe": "LaTeX2e",
    "TeX": "TeX",
    "BibTeX": "BibTeX",
    "XeTeX": "XeTeX",
    "LuaTeX": "LuaTeX",
    "og": "«\u00a0",
    "fg": "\u00a0»",
    "guillemotleft": "«",
    "guillemotright": "»",
    "textquotedblleft": "“",
    "textquotedblright": "”",
    "textendash": "–",
    "textemdash": "—",
    "textdegree": "°",
    "degree": "°",
    "celsius": "°C",
    "textbackslash": "\\",
    "textasciitilde": "~",
    "textbar": "|",
    "textless": "<",
    "textgreater": ">",
    "copyright": "©",
    "textregistered": "®",
    "texttrademark": "™",
    "euro": "€",
    "pounds": "£",
    "%": "%",
    "&": "&",
    "$": "$",
    "#": "#",
    "_": "_",
    "{": "{",
    "}": "}",
}

SIUNITX_NUMBER_MACROS = frozenset(["num", "numlist", "numrange", "SI", "qty", "SIrange", "qtyrange", "SIlist", "qtylist", "ang"])
SIUNITX_UNIT_MACROS = frozenset(["si", "unit"])

LIST_ENVS = frozenset(
    [
        "itemize",
        "enumerate",
        "description",
        "compactitem",
        "compactenum",
        "compactdesc",
        "inparaenum",
        "asparaenum",
        "asparaitem",
        "checklist",
        "list",
        "tasks",
    ]
)
FLOAT_ENVS = frozenset(
    [
        "figure",
        "figure*",
        "table",
        "table*",
        "marginfigure",
        "margintable",
        "wrapfigure",
        "wraptable",
        "sidewaysfigure",
        "sidewaystable",
        "SCfigure",
        "SCtable",
        "algorithm",
        "algorithm*",
        "listing",
        "floatingfigure",
        "subfigure",
        "subtable",
    ]
)
MATH_ENVS = frozenset(
    [
        "equation",
        "equation*",
        "align",
        "align*",
        "gather",
        "gather*",
        "multline",
        "multline*",
        "flalign",
        "flalign*",
        "alignat",
        "alignat*",
        "eqnarray",
        "eqnarray*",
        "displaymath",
        "math",
        "dmath",
        "dmath*",
        "IEEEeqnarray",
        "IEEEeqnarray*",
    ]
)
TABULAR_ENVS = frozenset(
    [
        "tabular",
        "tabular*",
        "tabularx",
        "tabulary",
        "longtable",
        "longtable*",
        "tabu",
        "supertabular",
        "xtabular",
        "NiceTabular",
        "tblr",
    ]
)
# Environments whose body is raw text (not LaTeX).
VERBATIM_ENVS = frozenset(
    [
        "verbatim",
        "verbatim*",
        "Verbatim",
        "Verbatim*",
        "BVerbatim",
        "LVerbatim",
        "lstlisting",
        "minted",
        "comment",
        "filecontents",
        "filecontents*",
        "spverbatim",
        "tcblisting",
        "pycode",
        "pyconsole",
        "luacode",
        "luacode*",
        "sagesilent",
        "sageblock",
        "Code",
        "codebox",
        "CCSXML",
    ]
)
# Environments that are LaTeX but not prose.
SKIP_ENVS = frozenset(
    [
        "tikzpicture",
        "pgfpicture",
        "forest",
        "axis",
        "picture",
        "circuitikz",
        "algorithmic",
        "algorithmic*",
        "thebibliography",
        "tikzcd",
        "dot2tex",
        "pspicture",
        "lstlisting",
    ]
)
REMOVED_ENVS = frozenset(["comment"])
DOCUMENT_ENVS = frozenset(["document"])

# Explicit argument specifications, so that the parser attaches arguments
# to their macro (pylatexenc otherwise leaves unknown macros without args).
MACRO_ARGSPECS = {
    "caption": "*[{",
    "captionof": "*{[{",
    "subcaption": "[{",
    "sidecaption": "[{",
    "todo": "[{",
    "footnote": "[{",
    "footnotetext": "[{",
    "marginpar": "[{",
    "sidenote": "[[{",
    "marginnote": "[{[",
    "thanks": "{",
    "title": "[{",
    "subtitle": "{",
    "author": "[{",
    "date": "{",
    "affil": "[{",
    "affiliation": "{",
    "institute": "[{",
    "email": "{",
    "keywords": "{",
    "label": "{",
    "index": "[{",
    "glossary": "{",
    "vspace": "*{",
    "addvspace": "{",
    "hspace": "*{",
    "setlength": "{{",
    "addtolength": "{{",
    "settowidth": "{{",
    "setcounter": "{{",
    "addtocounter": "{{",
    "stepcounter": "{",
    "refstepcounter": "{",
    "newcounter": "{[",
    "DeclareMathOperator": "*{{",
    "newtheorem": "*{[{[",
    "theoremstyle": "{",
    "usepackage": "[{[",
    "RequirePackage": "[{[",
    "documentclass": "[{[",
    "bibliography": "{",
    "bibliographystyle": "{",
    "addbibresource": "[{",
    "printbibliography": "[",
    "hypersetup": "{",
    "sisetup": "{",
    "graphicspath": "{",
    "pagestyle": "{",
    "thispagestyle": "{",
    "pagenumbering": "{",
    "linespread": "{",
    "definecolor": "[{{{",
    "colorlet": "[{[{",
    "selectlanguage": "{",
    "foreignlanguage": "[{{",
    "input": "{",
    "include": "{",
    "includeonly": "{",
    "subfile": "{",
    "import": "*{{",
    "subimport": "*{{",
    "includefrom": "{{",
    "includegraphics": "*[[{",
    "includesvg": "[{",
    "includepdf": "[{",
    "titleformat": "*{[{{{{[",
    "titlespacing": "*{{{{[",
    "tikzset": "{",
    "usetikzlibrary": "{",
    "pgfplotsset": "{",
    "newtcblisting": "[{{",
    "newtcolorbox": "[{[[{",
    "tcbuselibrary": "{",
    "newmdenv": "[{",
    "addto": "{{",
    "DeclareSIUnit": "[{{",
    "addcontentsline": "{{{",
    "markboth": "{{",
    "markright": "{",
    "lstset": "{",
    "lstnewenvironment": "{[[{{",
    "newminted": "[{{",
    "setminted": "[{",
    "DefineVerbatimEnvironment": "{{{",
    "crefname": "{{{",
    "Crefname": "{{{",
    "newacronym": "[{{{",
    "newglossaryentry": "{{",
    "geometry": "{",
    "setmainfont": "[{[",
    "setsansfont": "[{[",
    "setmonofont": "[{[",
    "setmainlanguage": "[{",
    "setdefaultlanguage": "[{",
    "setotherlanguage": "[{",
    "setotherlanguages": "{",
    "AtBeginDocument": "{",
    "pgfmathsetmacro": "{{",
    "captionsetup": "[{",
    "subcaptionbox": "{[{",
    "setcitestyle": "{",
    "specialrule": "{{{",
    "textcolor": "[{{",
    "color": "[{",
    "colorbox": "[{{",
    "fcolorbox": "[{{{",
    "href": "[{{",
    "hyperref": "[{",
    "hyperlink": "{{",
    "hypertarget": "{{",
    "multicolumn": "{{{",
    "multirow": "[{[{[{",
    "makebox": "[[{",
    "framebox": "[[{",
    "parbox": "[[[{{",
    "raisebox": "{[[{",
    "mbox": "{",
    "fbox": "{",
    "text": "{",
    "uline": "{",
    "uwave": "{",
    "sout": "{",
    "hl": "{",
    "enquote": "*{",
    "textquote": "*[[{",
    "foreignquote": "*{[[{",
    "textsuperscript": "{",
    "textsubscript": "{",
    "texttt": "{",
    "code": "{",
    "num": "[{",
    "numlist": "[{",
    "numrange": "[{{",
    "SI": "[{[{",
    "qty": "[{{",
    "SIrange": "[{{[{",
    "qtyrange": "[{{{",
    "SIlist": "[{[{",
    "qtylist": "[{{",
    "ang": "[{",
    "si": "[{",
    "unit": "[{",
    "item": "[",
    "crefrange": "*{{",
    "Crefrange": "*{{",
    "cmidrule": "[",
}
for _m in REF_MACROS:
    MACRO_ARGSPECS.setdefault(_m, "*{")
for _m in CITE_MACROS:
    MACRO_ARGSPECS.setdefault(_m, "*[[{")
for _m in SECTION_LEVELS:
    MACRO_ARGSPECS.setdefault(_m, "*[{")

ENV_ARGSPECS = {
    "tabular": "[{",
    "tabular*": "{[{",
    "tabularx": "{{",
    "tabulary": "{{",
    "longtable": "[{",
    "longtable*": "[{",
    "tabu": "{",
    "array": "[{",
    "minipage": "[[[{",
    "wrapfigure": "[{[{",
    "wraptable": "[{[{",
    "figure": "[",
    "figure*": "[",
    "table": "[",
    "table*": "[",
    "marginfigure": "[",
    "margintable": "[",
    "sidewaysfigure": "[",
    "sidewaystable": "[",
    "subfigure": "[{",
    "subtable": "[{",
    "SCfigure": "[[",
    "algorithm": "[",
    "listing": "[",
    "alignat": "{",
    "alignat*": "{",
    "multicols": "{",
    "multicols*": "{",
    "tcolorbox": "[",
    "mdframed": "[",
    "otherlanguage": "{",
    "otherlanguage*": "{",
    "thebibliography": "{",
    "theorem": "[",
    "lemma": "[",
    "proof": "[",
    "definition": "[",
    "corollary": "[",
    "proposition": "[",
    "remark": "[",
    "example": "[",
    "frame": "[{",
    "block": "{",
    "IEEEeqnarray": "{",
    "IEEEeqnarray*": "{",
}

# Verbatim environments that take standard arguments before their body.
VERBATIM_ENV_PREARGS = {
    "lstlisting": "[",
    "minted": "[{",
    "Verbatim": "[",
    "BVerbatim": "[",
    "LVerbatim": "[",
    "filecontents": "[{",
    "filecontents*": "[{",
    "tcblisting": "{",
}


@dataclass
class Definitions:
    """User definitions discovered by scanning LaTeX sources."""

    verbatim_envs: set[str] = field(default_factory=set)
    # name -> argspec for \newcommand with arguments
    macro_argspecs: dict[str, str] = field(default_factory=dict)
    # name -> category ('code', 'ref', 'cite', 'skip', 'text', 'other')
    macro_kinds: dict[str, str] = field(default_factory=dict)
    # zero-argument macros that expand to plain text
    text_macros: dict[str, str] = field(default_factory=dict)
    # macros the user asked to ignore (style-check "ignoredcommand")
    ignored_macros: set[str] = field(default_factory=set)
    ignored_envs: set[str] = field(default_factory=set)

    def merge(self, other: "Definitions") -> None:
        self.verbatim_envs |= other.verbatim_envs
        for k, v in other.macro_argspecs.items():
            self.macro_argspecs.setdefault(k, v)
        for k, v in other.macro_kinds.items():
            self.macro_kinds.setdefault(k, v)
        for k, v in other.text_macros.items():
            self.text_macros.setdefault(k, v)
        self.ignored_macros |= other.ignored_macros
        self.ignored_envs |= other.ignored_envs


_NEWCOMMAND_RE = re.compile(
    r"\\(?:re)?(?:newcommand|providecommand|DeclareRobustCommand)\*?\s*"
    r"(?:\{\s*\\([A-Za-z@]+)\s*\}|\\([A-Za-z@]+))\s*"
    r"(?:\[(\d)\])?\s*(\[[^\]]*\])?\s*\{"
)
_VERBATIM_DEF_RES = [
    re.compile(r"\\(?:re)?newtcblisting\s*(?:\[[^\]]*\])?\s*\{([A-Za-z@*]+)\}"),
    re.compile(r"\\lstnewenvironment\s*\{([A-Za-z@*]+)\}"),
    re.compile(r"\\DefineVerbatimEnvironment\s*\{([A-Za-z@*]+)\}"),
    re.compile(r"\\(?:re)?newenvironment\s*\{([A-Za-z@*]+)\}\s*(?:\[\d\])?\s*\{\s*\\(?:begin\{(?:verbatim|lstlisting|Verbatim)\}|verbatim|Verbatim)"),
]
_NEWMINTED_RE = re.compile(r"\\newminted\s*(?:\[([A-Za-z@*]+)\])?\s*\{([A-Za-z0-9@*+-]+)\}")


def _balanced_group(src: str, start: int) -> tuple[str, int] | None:
    """Return (content, end) of the brace group whose '{' is at start-1."""
    depth = 1
    i = start
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start:i], i + 1
        i += 1
    return None


_KIND_OF_WRAPPER = (
    ("code", CODE_MACROS),
    ("ref", REF_MACROS),
    ("cite", CITE_MACROS),
    ("skip", frozenset(["label", "index", "includegraphics", "vspace", "hspace"])),
)


def scan_definitions(src: str) -> Definitions:
    """Find user definitions that change how a document should be read."""
    defs = Definitions()
    for rx in _VERBATIM_DEF_RES:
        for m in rx.finditer(src):
            defs.verbatim_envs.add(m.group(1))
    for m in _NEWMINTED_RE.finditer(src):
        defs.verbatim_envs.add(m.group(1) or (m.group(2) + "code"))
    for m in _NEWCOMMAND_RE.finditer(src):
        name = m.group(1) or m.group(2)
        nargs = int(m.group(3) or 0)
        has_default = m.group(4) is not None
        body_info = _balanced_group(src, m.end())
        if body_info is None:
            continue
        body = body_info[0]
        if nargs == 0:
            text = _plain_text_of_body(body)
            if text is not None:
                defs.text_macros[name] = text
            continue
        spec = ("[" if has_default else "{") + "{" * (nargs - 1)
        defs.macro_argspecs[name] = spec
        defs.macro_kinds[name] = _classify_macro_body(body, defs)
    return defs


def _plain_text_of_body(body: str) -> str | None:
    """If a zero-argument macro body is simple text, return that text."""
    body = body.strip()
    if not body or len(body) > 60:
        return None
    # \emph{et al.}, \textit{e.g.}, \xspace...
    simplified = re.sub(r"\\(?:emph|textit|textsc|textrm|textsf|mbox|text|textup)\s*\{([^{}]*)\}", r"\1", body)
    simplified = re.sub(r"\\(?:xspace|@|/|\s)", "", simplified)
    simplified = simplified.replace("~", "\u00a0").replace("{}", "")
    if re.search(r"[\\{}$#^_&%]", simplified):
        return None
    return simplified


def _classify_macro_body(body: str, defs: Definitions) -> str:
    for m in re.finditer(r"\\([A-Za-z@]+)\*?\s*(?:\[[^\]]*\])?\s*\{[^{}]*#1", body):
        name = m.group(1)
        for kind, names in _KIND_OF_WRAPPER:
            if name in names:
                return kind
    m = re.search(r"\\begin\{([A-Za-z@*]+)\}[^#]*#1", body)
    if m and (m.group(1) in VERBATIM_ENVS or m.group(1) in defs.verbatim_envs or m.group(1) in SKIP_ENVS):
        return "code"
    return "text"


_BABEL_RE = re.compile(r"\\usepackage\s*\[([^\]]*)\]\s*\{[^}]*\bbabel\b[^}]*\}")
_POLYGLOSSIA_RE = re.compile(r"\\set(?:main|default)language\s*(?:\[[^\]]*\])?\s*\{([A-Za-z]+)\}")
_DOCCLASS_RE = re.compile(r"\\documentclass\s*\[([^\]]*)\]")

LANGUAGE_NAMES = {
    "french": "fr",
    "francais": "fr",
    "frenchb": "fr",
    "acadian": "fr",
    "canadien": "fr",
    "english": "en",
    "american": "en",
    "british": "en",
    "usenglish": "en",
    "ukenglish": "en",
    "canadian": "en",
    "australian": "en",
    "newzealand": "en",
}


def declared_language(src: str) -> str | None:
    """Return the main language declared with babel or polyglossia, if any."""
    m = _POLYGLOSSIA_RE.search(src)
    if m:
        return LANGUAGE_NAMES.get(m.group(1).lower())
    for rx in (_BABEL_RE, _DOCCLASS_RE):
        m = rx.search(src)
        if m:
            langs = [o.split("=")[-1].strip().lower() for o in m.group(1).split(",")]
            found = [LANGUAGE_NAMES[x] for x in langs if x in LANGUAGE_NAMES]
            if found:
                return found[-1]  # babel: the last option is the main language
    return None
