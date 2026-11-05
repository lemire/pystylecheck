# pystylecheck

A style checker for LaTeX papers, reports and theses that understands LaTeX.
Use it from the command line, in CI, or from an AI agent over MCP (Claude Code,
Codex, Gemini CLI, Grok CLI, Cursor, VS Code...).

pystylecheck is a **superset of [style-check.rb](https://github.com/nspring/style-check)**.
It reads the same rule files from the same places and reproduces style-check.rb's
output exactly in `--compat` mode. Because it parses the document, its rules see
the prose rather than the markup:

- A phrase is matched across line breaks and inside `\emph{}`: `\emph{very}↵unique`
  is "very unique".
- Nothing is reported inside math, `\verb`, `lstlisting`, `minted`, `\url`, citation
  keys, comments, `\iffalse` blocks or code environments you define yourself
  (`\newtcblisting`, `\lstnewenvironment`...).
- Reported columns are true source columns.

It also adds checks that need structure: duplicated words, headings not followed
by a paragraph, unreferenced figures, inconsistent spellings, and math typography.
It covers the useful parts of [lacheck](https://ctan.org/pkg/lacheck) without its
false positives, and many rules from Daniel Lemire's *Guide de rédaction des
rapports, des mémoires et des thèses*, including French typography.

```
$ pystylecheck sample.tex        # examples/sample.tex
sample.tex:3:1: error: \section{Results} starts directly with \subsection{Setup}: add an introductory paragraph [heading-without-paragraph]
    \section{Results}
    ^~~~~~~~~~~~~~~~~
sample.tex:5:30: error: repeated word: 'the the' [duplicate-word]
    We measure the throughput of the
                                 ^~~
sample.tex:6:16: error: you mean "many" [phrase]
    the decoder on a large number of inputs.
                   ^~~~~~~~~~~~~~~~~
sample.tex:7:13: error: use a non-breaking space: Figure~\ref{...} [ref-nbsp]
    As shown in Figure \ref{fig:speed}, the decoder is fast.~\cite{lemire2018}
                ^~~~~~~~~~~
sample.tex:7:56: error: the citation should precede the period: text~\cite{...}. [cite-after-period]
    As shown in Figure \ref{fig:speed}, the decoder is fast.~\cite{lemire2018}
                                                           ^~~~~~~~~~~~~~~~~~~
...
```

## Install

pystylecheck uses [uv](https://docs.astral.sh/uv/) and needs Python 3.11+.

```bash
uv tool install git+https://github.com/lemire/pystylecheck   # puts `pystylecheck` on your PATH
# or run it without installing:
uvx --from git+https://github.com/lemire/pystylecheck pystylecheck paper.tex
```

From a clone: `uv sync`, then `uv run pystylecheck paper.tex`. Run the tests with
`uv run pytest`.

## Usage

```bash
pystylecheck main.tex                # follows \input and \include
pystylecheck -v main.tex             # explain each kind of problem once (-vv: every time)
pystylecheck --min-severity info main.tex   # also show notes (long sentences, short sections...)
pystylecheck -f json main.tex        # machine-readable (also: html, github, style-check)
pystylecheck --diff main.tex         # show the safe fixes as a diff
pystylecheck --fix main.tex          # apply them
pystylecheck --list-checks
pystylecheck --explain heading-without-paragraph
```

Each finding has a severity:

- **error**: almost certainly wrong.
- **warning**: worth a look.
- **info**: advice. The text output hides notes unless you pass `--min-severity info`.

The exit status is 1 when there is an error (`-W` counts warnings too), so
pystylecheck can gate a build. `-f github` prints GitHub Actions annotations.

The language comes from `babel` or `polyglossia`. Without a declaration it is
guessed from the text; override it with `--lang fr` or `--lang en`. Files pulled in
by `\input` inherit the language of the main file.

### style-check.rb compatibility

| style-check.rb | pystylecheck |
|---|---|
| `style-check.rb *.tex` | `pystylecheck --compat *.tex` |
| `-v`, `-vv`, `-g`, `-w` | same options |
| `-r PATH` (override rule paths) | same option |
| `~/.style-checkrc` | read (gedit, verbose, web_output, override_rule_paths) |
| rule locations: `/etc/style-check.d/*`, `~/.style-check.d/*`, `~/.style-censor`, `./censor-dict`, `/etc/style-censor`, `./style-censor` | the same, plus `~/.config/pystylecheck/rules/*` |

`--compat` restricts pystylecheck to style-check.rb's rules and built-in checks and
prints its output format. On style-check.rb's test files the output is
byte-identical (see `tests/test_stylecheck_compat.py`). Without `--compat`, the
bundled style-check rules are always loaded. The same rule installed twice, for
example bundled and in `~/.style-check.d`, is reported only once.

## Checks

The rules from the style-check rule files are reported under their kind: `phrase`,
`spelling`, `capitalize` and `syntax`. The built-in checks:

| id | what | severity | lang | from |
|---|---|---|---|---|
| `abbreviation-spacing` | After an abbreviation inside a sentence, use `\ ` or `~` (English spacing) | warning | en | pystylecheck |
| `acronym-in-heading` | Acronyms in titles and headings | warning | fr | guide |
| `at-in-macro` | @ in macro names outside `\makeatletter ... \makeatother` | error | all | lacheck |
| `begin-end-argument` | `\begin` and `\end` need their {environment} argument on the same line | error | all | lacheck |
| `bitmap-figure` | Figures should be vector graphics (PDF, SVG, TikZ), not bitmaps (PNG, JPEG) | warning | all | guide |
| `bold-text` | Little or no bold in a scientific document | warning | all | guide |
| `capital-sentence-end` | A sentence ending with a capital letter needs `\@` before the period (NASA\@. The) | warning | en | lacheck |
| `caption-position` | Figure captions go below the figure, table captions above the table | warning | all | guide |
| `cite-after-period` | A citation should precede the period | error | all | style-check |
| `cite-as-noun` | A bracketed citation used as a noun ('in [3]') | error | all | style-check |
| `cite-nbsp` | Use a non-breaking space before `\cite` | warning | all | guide |
| `colored-text` | Text, including headings, is black | warning | all | guide |
| `consecutive-cites` | Merge consecutive citations: `\cite{a,b}` rather than `\cite{a}\cite{b}` | warning | all | guide |
| `decimal-separator` | French uses a decimal comma: 3,14 not 3.14 | warning | fr | guide |
| `display-math-punctuation` | A displayed formula is part of a sentence: end it with a period or a comma | warning | all | guide |
| `double-dollar` | Use `\[ ... \]` rather than `$$ ... $$` | warning | all | pystylecheck |
| `double-space` | Two spaces in a row from ~ (`~~`, `~` at the end of a line) | warning | all | lacheck |
| `duplicate-word` | The same word twice in a row ('the the') | error | all | pystylecheck |
| `ellipsis` | Write `\dots` (or …) rather than three periods | warning | all | lacheck |
| `float-placement` | Let LaTeX place floats: avoid [h], [H] and [h!] | warning | all | guide |
| `font-switch` | `\bf`, `\it`, `\tt`... are obsolete and take no argument: use `\textbf{}`, `\textit{}`, `\emph{}` | warning | all | lacheck |
| `footnote-space` | No space before `\footnote` | error | all | lacheck |
| `framed-float` | Do not put figures and tables in a box | warning | all | guide |
| `french-guillemets` | French quotes need non-breaking spaces inside: «~texte~» | warning | fr | guide |
| `hardcoded-reference` | Numbers typed by hand instead of `\ref` ('Figure 3') | warning | all | guide |
| `heading-period` | Headings do not end with a period | warning | all | pystylecheck |
| `heading-without-paragraph` | A heading must be followed by text, not by another heading, a list or an equation | error | all | guide |
| `inconsistent-spelling` | The same term written in different ways (Bozo3 / BOZO-3, e-mail / email) | warning | all | guide |
| `italic-correction` | Misplaced italic corrections: no `\/` before a period or comma, no double `\/` | warning | all | lacheck |
| `label-characters` | Labels should not contain spaces or special characters | warning | all | lacheck |
| `long-sentence` | Very long sentences (more than `max_sentence_words` words, default 30) | info | all | guide |
| `math-dots` | In math: `\cdots` between operators, `\ldots` between commas | warning | all | lacheck |
| `math-function-names` | Write `\sin`, `\log`, `\max`... in math, not sin, log, max | warning | all | guide |
| `math-punctuation` | Sentence punctuation goes outside inline math (`$x$.`) and inside displayed math | warning | all | lacheck |
| `math-starts-sentence` | A sentence should not start with a formula | warning | all | guide |
| `math-word-subscript` | Words in subscripts and superscripts should be upright: `x_{\mathrm{max}}` | warning | all | guide |
| `missing-include` | `\input` or `\include` of a file that cannot be found | info | all | lacheck |
| `paragraph-end` | Paragraphs should end with the end of a sentence | warning | all | style-check |
| `parenthesis-spacing` | Put a space before '(' and after ')' in running text | warning | all | guide |
| `percent-after-number` | A comment sign right after a number is usually a forgotten `\%` | error | all | style-check |
| `quote-direction` | Use ` `` ` to open and `''` to close quotations | warning | all | lacheck |
| `ref-capitalization` | Capitalize Table, Figure, Section... when they name a numbered element (English) | error | en | style-check |
| `ref-nbsp` | Figure, Table, Section... before `\ref` need a non-breaking space | error | all | style-check |
| `reference-style` | Refer to figures (tables, sections...) consistently: 'Fig.' or 'Figure', not both | warning | all | guide |
| `rules` | Phrases, spellings, capitalizations and syntax from the rule files | error | all | style-check |
| `sentence-capital` | A sentence should start with a capital letter | warning | all | guide |
| `short-section` | A section or subsection with a single paragraph | info | all | guide |
| `significant-digits` | Measured values should have at most 3 significant digits | info | all | guide |
| `single-sentence-paragraph` | A paragraph made of a single sentence | info | all | guide |
| `space-after-brace` | Unwanted space at the start of `\emph{ ...}`, `\textbf{ ...}` | warning | all | lacheck |
| `space-around-tie` | A space next to `~` produces a double space | warning | all | pystylecheck |
| `space-before-punctuation` | No space before a comma or a period (or ! and ? in English) | error | all | guide |
| `straight-quotes` | Straight double quotes "..." in LaTeX source | warning | all | pystylecheck |
| `stray-apostrophe` | An apostrophe after a space (« car ’elle »): probably a typo | warning | fr | pystylecheck |
| `subsection-reference` | Refer to subsections as sections ('Section~3.4' or '§~3.4') | warning | all | guide |
| `table-rules` | Tables: no vertical lines; use booktabs instead of `\hline` | warning | all | guide |
| `tex-primitive` | Plain TeX primitives in the document body (`\vskip`, `\over`, `\centerline`...) | warning | all | lacheck |
| `unbalanced` | Unbalanced `\begin`/`\end`, braces or `$` | error | all | lacheck |
| `unit-spacing` | Use a non-breaking space between a number and its unit (5~km, 12~\%), or siunitx | warning | all | guide |
| `unreferenced-float` | Every figure and table needs a caption, a `\label` and a reference in the text | warning | all | guide |
| `url-scheme` | `\url{}` should start with http://, https://, ftp:// or mailto: | error | all | style-check |
| `verb-newline` | `\verb` must end on the same line; no tabs in verbatim | error | all | lacheck |

"guide" marks rules from the *Guide de rédaction*. The French rule file
(`src/pystylecheck/rules/fr/guide`) adds its vocabulary advice: *méthodologie* →
*méthode*, *problématique*, adverbs such as *très*, the passive voice, negation,
and position words such as *ci-dessous* and *voici la figure*.

### How it compares with style-check.rb and lacheck

These numbers come from 345 `.tex` files of real papers, reviews and cover letters.

- **style-check.rb.** pystylecheck reports everything style-check.rb finds in
  prose. The style-check.rb findings it leaves out are all inside code, math,
  comments or command arguments, where they are false positives: `<` in a C++
  listing, a hyphen in `\code{-march=x86-64-v2}`, keywords in `\lstset{...}`, or
  `.~\cite` after "et al.".
- **lacheck.** pystylecheck covers the same problems. Every lacheck warning it
  does not repeat is a lacheck false positive:
  - `{` followed by a newline in `\sisetup{` blocks;
  - code inside listings;
  - `.NET`;
  - `Figures~\ref{a}, \ref{b}`;
  - environments whose `\begin` and `\end` sit in a `\newenvironment` definition;
  - `@` between `\makeatletter` and `\makeatother`;
  - TikZ `\foreach {1,...,5}`.
- **Fixed limitations.** Accented letters count as letters, and the English
  spacing checks are skipped under `\frenchspacing` or babel-french.

## Controlling checks

On the command line:

```bash
pystylecheck --disable long-sentence,bold-text main.tex
pystylecheck --disable phrase main.tex          # a rule kind: phrase, spelling, capitalize, syntax
pystylecheck --disable @passive-voice main.tex  # a whole rule file
pystylecheck --only duplicate-word,heading-without-paragraph main.tex
```

In the document, with LaTeX comments:

```latex
We test that that works.  % pystylecheck: ignore=duplicate-word
% pystylecheck: ignore-next-line
\section{SIMD}
% pystylecheck: disable=long-sentence
...
% pystylecheck: enable=long-sentence
```

In a configuration file, `.pystylecheck.toml` (searched from the file's directory
upward), `[tool.pystylecheck]` in `pyproject.toml`, or
`~/.config/pystylecheck/config.toml`:

```toml
language = "fr"
disable = ["bold-text", "long-sentence"]
enable = ["acronym-in-heading"]          # e.g. for English documents too
rules = ["~/my-rules"]                    # extra rule files or directories
plugins = ["mychecks"]                    # Python modules or .py files
ignored_commands = ["todo", "hostname"]   # arguments are not prose
ignored_environments = ["mycode"]
max_sentence_words = 25
max_significant_digits = 3
duplicate_allowed = ["very"]
acronyms_allowed = ["GPU"]
severity = { "bold-text" = "info" }
```

## Extending

### Rule files

Rule files use style-check.rb's format: a regular expression, then `%`, a kind and an
explanation.

```
a large number of   % phrase you mean "many"
Planetlab           % capitalize PlanetLab
teh                 % spelling
[ ]\\footnote       % syntax no space before footnote.
todo                % ignoredcommand
```

The kinds work as follows:

- `syntax`: matched against the source, with comments removed and math, verbatim
  and ignored arguments masked.
- `phrase`: case-insensitive, whole words; a space matches any whitespace.
- `spelling`: case-insensitive, whole words.
- `capitalize`: case-sensitive, whole words.

`phrase`, `spelling` and `capitalize` rules run on the prose, unless they mention
LaTeX (a backslash, `~`, a brace, `$`), in which case they run on the source.

pystylecheck adds two kinds:

- `prose`: a case-sensitive regex on the prose.
- `ignoredenvironment`: an environment whose body is not prose.

An explanation that ends with `?` marks a weak rule, reported as a warning.
`# pystylecheck: lang=fr` at the top of a file restricts it to French documents.

### Python checks

```python
# mychecks.py
import re
from pystylecheck.checks import Check, register

@register
class NoTodo(Check):
    id = "no-todo"
    description = "TODO markers left in the text"
    severity = "error"

    def check(self, doc, ctx):
        for block in doc.blocks:              # paragraphs, headings, captions, footnotes...
            for m in re.finditer(r"\bTODO\b", block.text):
                yield ctx.at_prose(self, doc, block, m.start(), m.end(), "remove the TODO")
```

Load it with `--plugin mychecks.py`, `plugins = [...]` in the configuration, or a
`pystylecheck.checks` entry point in a package. A check sees a parsed `Document`:

- `blocks`: prose with a source offset for every character, so findings land on
  the right line and column;
- `events`: the structure (headings, paragraphs, lists, floats);
- `floats`, `tabulars`, `maths`, `labels`, `refs` and `cites`;
- `source_view`: the masked source.

For checks across files, subclass `ProjectCheck`.

From Python:

```python
from pystylecheck import check_files
report = check_files(["main.tex"], language="en")
for f in report.findings:
    print(f.line, f.column, f.check, f.message)
```

## Use it from an AI agent

`pystylecheck mcp` runs an [MCP](https://modelcontextprotocol.io) server over stdio
with four tools:

| tool | |
|---|---|
| `check_latex` | check files (`paths`) or LaTeX `text`; returns findings with line, column, severity, message and, when available, a safe `replacement` |
| `fix_latex` | apply the safe fixes; returns a diff (`dry_run` is on by default) |
| `list_style_checks` | the checks, optionally for one language |
| `explain_check` | the rationale for a check |

`pystylecheck mcp --setup` prints these commands for your machine.

### Claude Code

```bash
claude mcp add --scope user --transport stdio pystylecheck -- uvx --from git+https://github.com/lemire/pystylecheck pystylecheck mcp
```

You can also install the skill, so that Claude knows when and how to use the tool,
even with MCP turned off:

```bash
mkdir -p ~/.claude/skills && cp -R skills/pystylecheck ~/.claude/skills/
```

Then ask: "check my thesis with pystylecheck and fix the clear mistakes".

### OpenAI Codex CLI

```bash
codex mcp add pystylecheck -- uvx --from git+https://github.com/lemire/pystylecheck pystylecheck mcp
```

### Google Gemini CLI

```bash
gemini mcp add --scope user pystylecheck uvx --from git+https://github.com/lemire/pystylecheck pystylecheck mcp
```

### xAI Grok CLI

```bash
grok mcp add pystylecheck -- uvx --from git+https://github.com/lemire/pystylecheck pystylecheck mcp
```

Or by hand in `~/.grok/config.toml`:

```toml
[mcp_servers.pystylecheck]
command = "uvx"
args = ["--from", "git+https://github.com/lemire/pystylecheck", "pystylecheck", "mcp"]
```

### Cursor, VS Code and other clients

```bash
cursor --add-mcp '{"name":"pystylecheck","command":"uvx","args":["--from","git+https://github.com/lemire/pystylecheck","pystylecheck","mcp"]}'
code   --add-mcp '{"name":"pystylecheck","command":"uvx","args":["--from","git+https://github.com/lemire/pystylecheck","pystylecheck","mcp"]}'
```

Other clients take the common JSON form:

```json
{ "mcpServers": { "pystylecheck": { "command": "uvx",
  "args": ["--from", "git+https://github.com/lemire/pystylecheck", "pystylecheck", "mcp"] } } }
```

If you installed it with `uv tool install`, use `pystylecheck` with the argument
`mcp` instead of the `uvx` command.

### Agents without MCP

Any agent that can run shell commands can use `pystylecheck -f json file.tex`. Put
[`skills/pystylecheck/SKILL.md`](skills/pystylecheck/SKILL.md) in its instructions
(for example in `AGENTS.md`).

## License

GPL-3.0-or-later. The rule files in `src/pystylecheck/rules/en` and the test files
in `tests/data/style-check` come from Neil Spring's
[style-check](https://github.com/nspring/style-check) (GPL-3.0). The checks marked
"lacheck" were rewritten from the behaviour of Kresten Krab Thorup's lacheck; no
lacheck code is included.
