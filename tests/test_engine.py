"""Rules, configuration, suppression, includes, fixes, plugins, MCP."""

import json
import textwrap

from conftest import ids

from pystylecheck.config import Options
from pystylecheck.engine import StyleChecker, apply_fixes
from pystylecheck.latex import parse
from pystylecheck.rules import compile_rule, load_rules


def test_rule_compilation_like_style_check():
    rx, target = compile_rule("a large number of", "phrase")
    assert target == "prose" and rx.search("A LARGE\nnumber of")
    rx, target = compile_rule("section~\\\\ref", "capitalize")
    assert target == "source"
    rx, _ = compile_rule("PlanetLab", "capitalize")
    assert rx.search("PlanetLab") and not rx.search("planetlab")


def test_bundled_rules_all_compile():
    rs = load_rules(use_user=False)
    assert not [e for e in rs.errors if "Error" in e]
    assert len(rs.rules) > 780
    assert {"todo", "texttt"} <= rs.ignored_commands


def test_phrase_rules_see_prose_not_markup(tmp_path, check):
    rules = tmp_path / "r"
    rules.write_text("very unique % phrase unique is.\nplanetlab % capitalize PlanetLab\n")
    fs = check("It is \\emph{very}\nunique. See \\url{http://planetlab.org} and $very unique$.", override_rules=[str(rules)])
    assert [f.check for f in fs if f.check in ("phrase", "capitalize")] == ["phrase"]


def test_weak_rules_are_warnings(tmp_path, check):
    rules = tmp_path / "r"
    rules.write_text("fashion % phrase hrm?\nleverage % phrase use\n")
    fs = {f.matched: f for f in check("In this fashion we leverage it.", override_rules=[str(rules)])}
    assert fs["fashion"].severity == "warning" and fs["fashion"].message == "hrm"
    assert fs["leverage"].severity == "error"


def test_ignoredcommand_and_ignoredenvironment(tmp_path, check):
    rules = tmp_path / "r"
    rules.write_text("leverage % phrase use\nmynote % ignoredcommand\nmybox % ignoredenvironment\n")
    src = "\\mynote{we leverage}\n\\begin{mybox}\nleverage\n\\end{mybox}\nWe leverage it."
    fs = [f for f in check(src, override_rules=[str(rules)]) if f.check == "phrase"]
    assert [f.line for f in fs] == [5]


def test_inline_suppressions(check):
    src = "the the % pystylecheck: ignore\nthe the % pystylecheck: ignore=long-sentence\n% pystylecheck: ignore-next-line\nthe the\nthe the\n"
    lines = sorted(f.line for f in check(src) if f.check == "duplicate-word")
    assert lines == [2, 5]


def test_disable_by_kind_file_and_id(check):
    src = "In order to leverage the the cat."
    assert "duplicate-word" not in ids(check(src, disable=["duplicate-word"]))
    assert "phrase" not in ids(check(src, disable=["phrase"]))
    assert ids(check(src, only=["duplicate-word"])) == ["duplicate-word"]


def test_language_detection():
    assert parse("a", "\\documentclass{article}\\usepackage[english,french]{babel}").language == "fr"
    assert parse("a", "\\setmainlanguage{english}").language == "en"
    fr = "Le chat est dans la maison et nous sommes pour une solution avec les données de cette étude qui sont sur la table."
    assert parse("a", fr).language == "fr"


def test_user_defined_code_environment(check):
    src = "\\newtcblisting{margcode}{listing only}\n\\begin{margcode}\nthe the < x\n\\end{margcode}\nDone."
    assert "duplicate-word" not in ids(check(src))
    assert "syntax" not in ids(check(src))


def test_user_text_macro_expansion():
    d = parse("a", "\\newcommand{\\etal}{\\emph{et al.}\\xspace}\nSmith \\etal{} show.")
    assert "et al." in d.blocks[-1].text


def test_follow_includes_and_language_inheritance(tmp_path):
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n\\usepackage[french]{babel}\n\\begin{document}\n\\input{chap}\n\\end{document}\n")
    (tmp_path / "chap.tex").write_text("Le le chat est là.\n")
    rep = StyleChecker(Options(user_rules=False)).check_paths([str(tmp_path / "main.tex")])
    assert {d.path.split("/")[-1]: d.language for d in rep.documents} == {"main.tex": "fr", "chap.tex": "fr"}
    assert any(f.check == "duplicate-word" and f.path.endswith("chap.tex") for f in rep.findings)


def test_apply_fixes():
    src = "See Figure \\ref{f} and the the end~ \\cite{x}."
    rep = StyleChecker(Options(user_rules=False)).check_text(src, "t.tex")
    (old, new), = apply_fixes(rep).values()
    assert new == "See Figure~\\ref{f} and the end~\\cite{x}."


def test_config_file(tmp_path, monkeypatch):
    (tmp_path / ".pystylecheck.toml").write_text('disable = ["duplicate-word"]\nmax_sentence_words = 5\n')
    from pystylecheck.config import load_options

    opts, warnings = load_options(str(tmp_path))
    assert opts.disable == ["duplicate-word"] and opts.max_sentence_words == 5 and not warnings


def test_plugin(tmp_path):
    plugin = tmp_path / "myplug.py"
    plugin.write_text(textwrap.dedent('''
        import re
        from pystylecheck.checks import Check, register

        @register
        class NoTodo(Check):
            id = "no-todo"
            description = "TODO left in text"
            severity = "error"

            def check(self, doc, ctx):
                for b in doc.blocks:
                    for m in re.finditer(r"\\bTODO\\b", b.text):
                        yield ctx.at_prose(self, doc, b, m.start(), m.end(), "remove TODO")
    '''))
    rep = StyleChecker(Options(user_rules=False, plugins=[str(plugin)])).check_text("Some TODO here.", "t.tex")
    assert [f.check for f in rep.findings if f.check == "no-todo"] == ["no-todo"]


def test_json_output_and_exit_status(tmp_path):
    from pystylecheck.cli import main

    f = tmp_path / "a.tex"
    f.write_text("The the cat.\n")
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        status = main(["--no-user-rules", "-f", "json", str(f)])
    data = json.loads(buf.getvalue())
    assert status == 1 and data["summary"]["error"] >= 1


def test_mcp_check_function(tmp_path):
    from pystylecheck.mcp_server import _report_dict, run_check

    rep = run_check(text="\\section{A}\n\\section{B}\nThe the end.", filename="x.tex")
    d = _report_dict(rep, 100)
    assert {"heading-without-paragraph", "duplicate-word"} <= {f["check"] for f in d["findings"]}
    assert all("line" in f and "message" in f for f in d["findings"])


def test_mcp_server_builds():
    from pystylecheck.mcp_server import build_server

    assert build_server() is not None
