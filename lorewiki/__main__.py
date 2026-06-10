"""Allow running the CLI via ``python -m lorewiki``."""

from lorewiki.cli import app

if __name__ == "__main__":  # pragma: no cover - exercised by subprocess tests
    app()
