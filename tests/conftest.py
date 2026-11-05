import pytest

from pystylecheck.config import Options
from pystylecheck.engine import StyleChecker


@pytest.fixture
def check():
    """check(text, **options) -> list of findings (user rule files are never loaded)."""

    def run(text, path="t.tex", **opts):
        opts.setdefault("user_rules", False)
        return StyleChecker(Options(**opts)).check_text(text, path).findings

    return run


def ids(findings):
    return [f.check for f in findings]
