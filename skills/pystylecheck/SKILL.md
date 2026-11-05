---
name: pystylecheck
description: Check LaTeX papers, reports and theses for style problems (wordy phrases, repeated words, headings without text, \ref/\cite spacing, figure and table conventions, math typography, French typography) with pystylecheck, then fix what is clearly wrong. Use when the user asks to proofread, style-check, lint or polish a .tex document, or before submitting one.
---

# pystylecheck: style checking for LaTeX

pystylecheck parses LaTeX: it reports problems in the prose, never in math, code,
URLs or comments, with exact line and column. **Use the MCP tools (`check_latex`,
`fix_latex`, `explain_check`, `list_style_checks`) if they are available.** Otherwise
use the CLI; the workflow is the same.

## Run it

- Give it the **main file** (the one with `\begin{document}`): it follows `\input`
  and `\include`, and the project-wide checks (unreferenced figures, inconsistent
  spellings, reference style) need the whole document.
- MCP: `check_latex` with `paths: ["/abs/path/main.tex"]` (absolute paths), or `text`
  for a snippet. Pass `min_severity: "warning"` for a first pass on a long document.
- CLI: `pystylecheck -f json main.tex` (or `uvx --from git+https://github.com/lemire/pystylecheck pystylecheck -f json main.tex`).
  The JSON has `summary` and `findings`: `path`, `line`, `column`, `end_line`,
  `end_column`, `severity`, `check`, `message`, `matched`, and sometimes `replacement`.
  Exit status 1 means errors were found; it is not a failure of the tool.

## Act on the findings

1. **Severity.** `error` is almost always a real mistake: fix it. `warning` deserves a
   look: fix it when the message is right in context. `info` (long sentences, short
   sections, significant digits) is advice for the author: report it, don't rewrite
   on your own.
2. **Safe fixes.** Findings with a `replacement` are mechanical fixes (`Figure~\ref`,
   `~\cite{x}.`, removing a repeated word, `\sin`...). Apply them with `fix_latex`
   (review the `diff` from the default `dry_run`, then call again with
   `dry_run: false`), or `pystylecheck --diff` / `--fix` on the CLI, or edit the
   matched text yourself.
3. **Style rules are not grammar.** `phrase`, `spelling`, `capitalize` and `syntax`
   findings come from rule files ("a large number of" → "many", passive voice...).
   Keep the author's voice. Change wording only when the suggestion is clearly better
   or the user asked for a thorough edit, and never change technical meaning.
4. **Structure findings** (`heading-without-paragraph`, `short-section`,
   `unreferenced-float`) usually need the author: when there is no obvious fix, tell
   the user rather than inventing content.
5. Use `explain_check` (or `pystylecheck --explain <check>`) when a finding is unclear.

## False positives

Leave the text alone and suppress the finding on that line:
`% pystylecheck: ignore=<check>` at the end of the line, or
`% pystylecheck: ignore-next-line` above it. For a whole project, add a
`.pystylecheck.toml` next to the main file with `disable = ["<check>"]`. Do not
suppress findings just to make the output clean: tell the user what you suppressed.

## Language

The language comes from babel or polyglossia, else it is guessed. For French documents
the French guide rules apply (guillemets, decimal comma, units, *méthodologie*...).
Force it with `language: "fr"` (MCP) or `--lang fr` (CLI) if the guess is wrong.
