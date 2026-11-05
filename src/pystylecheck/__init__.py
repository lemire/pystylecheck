"""pystylecheck: a LaTeX-aware style checker, superset of style-check.rb."""

__version__ = "0.1.0"


def check_text(text: str, path: str = "<text>", **options):
    """Check LaTeX source text; return a Report. Options are Options fields."""
    from .config import Options
    from .engine import StyleChecker

    return StyleChecker(Options(**options)).check_text(text, path)


def check_files(paths, **options):
    """Check LaTeX files; return a Report."""
    from .config import Options
    from .engine import StyleChecker

    return StyleChecker(Options(**options)).check_paths(list(paths))


__all__ = ["__version__", "check_text", "check_files"]
