"""Verify the ``python -m lorewiki`` entrypoint works as a subprocess.

We spawn a real subprocess instead of importing ``lorewiki.__main__`` so we
exercise the path Python uses for module-as-script execution, which is what
end users actually hit.
"""

from __future__ import annotations

import subprocess
import sys

from lorewiki import __version__


def _run_lorewiki_subprocess(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``python -m lorewiki ...`` and decode stdout as UTF-8.

    On Windows, ``text=True`` defaults to the system code page (cp936/GBK)
    which crashes on the CJK arrows Typer puts in --help. The CLI's own
    reconfigure doesn't help us here because pytest's capture is what the
    child inherits as stdout.
    """
    return subprocess.run(
        [sys.executable, "-m", "lorewiki", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )


def test_python_m_lorewiki_version() -> None:
    result = _run_lorewiki_subprocess(["--version"])
    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout


def test_python_m_lorewiki_help_contains_subcommands() -> None:
    result = _run_lorewiki_subprocess(["--help"])
    assert result.returncode == 0, result.stderr
    for cmd in ("init", "index", "search", "ask", "config", "topic"):
        assert cmd in result.stdout, f"sub-command {cmd!r} missing from --help"
