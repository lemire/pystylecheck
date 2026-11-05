"""Behaviour of individual checks, including what they must NOT flag."""

from conftest import ids


def only(findings, cid):
    return [f for f in findings if f.check == cid]


DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"


# -- duplicated words -----------------------------------------------------------

def test_duplicate_word_across_line_and_markup(check):
    fs = only(check("We saw the\nthe cat and \\emph{a} a dog."), "duplicate-word")
    assert [f.line for f in fs] == [1, 2]
    assert fs[0].replacement == ""


def test_duplicate_word_exceptions(check):
    assert not only(check("He said that that was fine. We want AND and OR."), "duplicate-word")
    assert not only(check("Nous nous demandons si cela fonctionne bien.", language="fr"), "duplicate-word")
    assert not only(check("the $x$ the and \\cite{a} \\cite{b}"), "duplicate-word")


def test_duplicate_word_ignores_code_and_comments(check):
    assert not only(check("Use \\texttt{the the} here. % the the\n"), "duplicate-word")


# -- headings ---------------------------------------------------------------------

def test_heading_followed_by_heading(check):
    fs = only(check(DOC % "\\section{Intro}\n\\subsection{Detail}\nText here.\n"), "heading-without-paragraph")
    assert len(fs) == 1 and "starts directly with" in fs[0].message


def test_heading_at_end_and_followed_by_list(check):
    fs = only(check("\\section{A}\n\\begin{itemize}\\item x\\end{itemize}\n\\section{B}\n"), "heading-without-paragraph")
    assert [f.line for f in fs] == [1, 3]


def test_heading_followed_by_float_then_text_is_fine(check):
    src = DOC % "\\section{A}\n\\begin{figure}\\centering\\caption{C}\\label{f}\\end{figure}\nSome text, see Figure~\\ref{f}.\n"
    assert not only(check(src), "heading-without-paragraph")


def test_heading_followed_by_formula(check):
    fs = only(check("\\section{A}\n\\[ x = 1. \\]\nThen text.\n"), "heading-without-paragraph")
    assert len(fs) == 1


# -- references and citations -------------------------------------------------------

def test_ref_nbsp_with_fix(check):
    fs = only(check("See Figure \\ref{f} and Table\n\\ref{t}."), "ref-nbsp")
    assert len(fs) == 2
    assert fs[0].replacement == "Figure~\\ref"


def test_cite_after_period_fix(check):
    fs = only(check("As shown.~\\cite{x} Next."), "cite-after-period")
    assert fs and fs[0].replacement == "~\\cite{x}."
    assert not only(check("Smith et al.~\\cite{x} show it."), "cite-after-period")


def test_cite_as_noun(check):
    assert only(check("This is explained in~\\cite{x}."), "cite-as-noun")
    assert not only(check("Smith et al.~\\cite{x} show that it works."), "cite-as-noun")


def test_consecutive_cites(check):
    fs = only(check("Known~\\cite{a}\\cite{b}."), "consecutive-cites")
    assert fs and fs[0].replacement == "\\cite{a,b}"


def test_hardcoded_reference(check):
    assert only(check("As Figure 3 shows, it works."), "hardcoded-reference")
    assert not only(check("As Figure~\\ref{x} shows, it works."), "hardcoded-reference")


def test_unreferenced_float(check):
    src = DOC % ("Text.\n\\begin{figure}\\caption{A}\\label{fig:a}\\end{figure}\n"
                 "\\begin{table}\\caption{B}\\label{tab:b}\\end{table}\nSee Table~\\ref{tab:b}.\n")
    fs = only(check(src), "unreferenced-float")
    assert len(fs) == 1 and "fig:a" in fs[0].message


def test_reference_style_consistency(check):
    src = "See Figure~\\ref{a}, Figure~\\ref{b} and Fig.~\\ref{c}."
    fs = only(check(src), "reference-style")
    assert len(fs) == 1 and fs[0].matched == "Fig."


# -- structure ------------------------------------------------------------------

def test_paragraph_end(check):
    fs = only(check("This paragraph has no final period at all\n\nNext one is fine.\n"), "paragraph-end")
    assert len(fs) == 1 and fs[0].line == 1


def test_paragraph_end_not_for_commands_or_lists(check):
    src = "\\maketitle\n\n\\ccsdesc[500]{Information systems~Browsers}\n\nWe have the following:\n\\begin{itemize}\\item a\\end{itemize}\n"
    assert not only(check(src), "paragraph-end")


def test_short_section_and_single_sentence(check):
    src = "\\section{A}\nOnly one sentence in this section here.\n\n\\section{B}\nOne. Two. Three.\n\nFour. Five.\n"
    assert [f.line for f in only(check(src), "short-section")] == [1]
    assert [f.line for f in only(check(src), "single-sentence-paragraph")] == [2]


def test_acronym_in_french_heading(check):
    fs = only(check("\\section{Les instructions SIMD}\nTexte. Encore. Plus.", language="fr"), "acronym-in-heading")
    assert fs and "SIMD" in fs[0].message


# -- prose ------------------------------------------------------------------------

def test_sentence_capital_and_abbreviations(check):
    fs = only(check("This works. but this does not. We use e.g.\\ apples, i.e.\\ fruit. See (most?) of them."), "sentence-capital")
    assert [f.matched for f in fs] == ["but"]


def test_space_before_punctuation(check):
    fs = only(check("A word , then a period ."), "space-before-punctuation")
    assert len(fs) == 2
    assert not only(check("We use .NET and \\label{x}, fine."), "space-before-punctuation")


def test_french_allows_space_before_exclamation(check):
    assert not only(check("Bonjour ! Comment allez-vous ?", language="fr"), "space-before-punctuation")


# -- typography and math --------------------------------------------------------

def test_math_function_names_and_subscripts(check):
    fs = check("We have $f(x) = sin(x_{temps}) + \\log y + \\text{max}$.")
    assert [f.matched for f in only(fs, "math-function-names")] == ["sin"]
    assert [f.matched for f in only(fs, "math-word-subscript")] == ["temps"]


def test_display_math_punctuation(check):
    fs = only(check("The formula is\n\\[ x = 1 \\]\nThe next sentence.\n"), "display-math-punctuation")
    assert fs
    assert not only(check("The formula is\n\\[ x = 1, \\]\nwhere $x$ is one.\n"), "display-math-punctuation")


def test_french_typography(check):
    fs = check("Il est à 3.14 de « là » et 12\\% du reste.", language="fr")
    assert only(fs, "decimal-separator")
    assert len(only(fs, "french-guillemets")) == 2
    assert only(fs, "unit-spacing")
    assert not only(check("Voir la version 3.12 et le DOI 10.1109/ICCV.", language="fr"), "decimal-separator")


def test_significant_digits(check):
    fs = only(check("The time was 1.234 s while the other was 1.2 s."), "significant-digits")
    assert [f.matched for f in fs] == ["1.234"]


def test_floats_and_tables(check):
    src = DOC % ("\\begin{figure}[h]\\caption{Cap}\\includegraphics{plot.png}\\label{f}\\end{figure}\n"
                 "See Figure~\\ref{f} and Table~\\ref{t}.\n"
                 "\\begin{table}\\begin{tabular}{|l|r|}\\hline a & b\\\\\\hline\\end{tabular}\\caption{T}\\label{t}\\end{table}\n")
    fs = check(src)
    for cid in ("float-placement", "caption-position", "bitmap-figure", "table-rules"):
        assert only(fs, cid), cid
    assert len(only(fs, "caption-position")) == 2


def test_inconsistent_spelling(check):
    src = DOC % "We use PlanetLab. PlanetLab is fine. Planetlab is not. Send an e-mail or an email.\n\n\\section{Compile-Time Hashing}\nWe hash at compile-time. Again compile-time."
    fs = only(check(src, only=["inconsistent-spelling"]), "inconsistent-spelling")
    msgs = " ".join(f.message for f in fs)
    assert "Planetlab" in msgs and "e-mail" in msgs
    assert "Compile-Time" not in msgs


# -- lacheck-like checks ------------------------------------------------------------

def test_lacheck_family(check):
    src = DOC % ("We use NASA. The agency works~~well and \\bf{bold} text. Dots... and $x.$ end.\n"
                 "More \\footnote{x}. \\vskip 1em See \\emph{ spaced} and \\label{bad label} and ''wrong`` quotes.\n"
                 "\\[ y = x_1 + \\ldots + x_n \\]. Done \\foo@bar.\n\\begin{itemize}\n\\item x\n\\end{enumerate}\n")
    got = set(ids(check(src)))
    for cid in ("capital-sentence-end", "double-space", "font-switch", "ellipsis", "math-punctuation",
                "footnote-space", "tex-primitive", "space-after-brace", "label-characters", "quote-direction",
                "math-dots", "at-in-macro", "unbalanced"):
        assert cid in got, cid


def test_lacheck_false_positives_avoided(check):
    src = DOC % ("\\sisetup{\n  locale = FR\n}\n\\makeatletter\\let\\@foo\\relax\\makeatother\n"
                 "Figures~\\ref{a}, \\ref{b} and \\ref{c} show it.\n"
                 "\\begin{lstlisting}\nx = a ... b; if (x != 0) {\n\\end{lstlisting}\n"
                 "\\begin{tikzpicture}\\foreach \\x in {1,...,5} {}\\end{tikzpicture}\n")
    got = set(ids(check(src)))
    for cid in ("space-after-brace", "at-in-macro", "ellipsis", "math-dots", "unbalanced", "space-before-punctuation", "ref-nbsp"):
        assert cid not in got, cid


def test_frenchspacing_disables_english_spacing_checks(check):
    src = "\\frenchspacing\nWe use NASA. The agency, e.g. the one, works."
    got = set(ids(check(src)))
    assert "capital-sentence-end" not in got and "abbreviation-spacing" not in got


def test_inconsistent_spelling_only_in_headings(check):
    src = "\\section{Fast Compile-Time Hashing}\nText. More. Again.\n\\section{Compile-time Tricks}\nText. More. Again.\n\\section{Compiletime Done}\nEnd. Fin. Yes."
    fs = only(check(src, only=["inconsistent-spelling"]), "inconsistent-spelling")
    assert len(fs) == 1
