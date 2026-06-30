"""Top-level CLI package.

Importing this package side-effect-imports every command module so
that all ``@app.command()`` / ``@config_app.command()`` /
``@topic_app.command()`` decorators fire. The single ``app`` symbol
exposed here is what the ``lorewiki`` console-script entry point
binds to.
"""

from __future__ import annotations

# Order matters: ``apps`` first because every other module imports the
# Typer instances / console from it. ``helpers`` is dependency-free.
from lorewiki.cli import (
    add,  # noqa: F401  (registers `lorewiki add`)
    apps,  # noqa: F401  (side-effect: import decorators register)
    commands,  # noqa: F401  (registers init / index / …)
    config_cmds,  # noqa: F401  (registers config list / get / set)
    delete,  # noqa: F401  (registers `lorewiki delete`)
    helpers,  # noqa: F401  (side-effect: re-export symbols)
    inject_cmd,  # noqa: F401  (registers `lorewiki inject`)
    install_cmd,  # noqa: F401  (registers `lorewiki install`)
    mcp_cmd,  # noqa: F401  (registers `lorewiki mcp serve`)
    topic_cmds,  # noqa: F401  (registers topic …)
    update,  # noqa: F401  (registers `lorewiki update`)
)
from lorewiki.cli.apps import app  # re-exported for the entry point
from lorewiki.cli.helpers import print_phase_status  # re-exported for tests

__all__ = ["app", "print_phase_status"]
