"""``lorewiki install`` — install / uninstall / inspect the agent skill.

This is the wheel-side counterpart of the source-tree
``skills/install.py``. A user who installed ``lorewiki`` from PyPI
runs ``lorewiki install`` (no need to clone the repository); a
developer who already has the source tree checked out can still
use ``python skills/install.py`` — the two paths share the same
TOOL catalog, prompt grammar, and install semantics.
"""
from __future__ import annotations

from typing import Annotated

import typer

from lorewiki.cli.apps import app
from lorewiki.utils.skill_installer import run as _run


@app.command()
def install(
    tool: Annotated[
        str | None,
        typer.Option(
            "--tool",
            help=(
                "Comma-separated tool ids to install into (e.g. "
                "'opencode,claude,codex'). If omitted and --all is also "
                "omitted, an interactive multi-select prompt is shown."
            ),
        ),
    ] = None,
    all_: Annotated[
        bool,
        typer.Option(
            "--all",
            help=(
                "Install into every detected tool without prompting. "
                "A tool is 'detected' when its config root "
                "(e.g. ~/.config/opencode) already exists on this machine."
            ),
        ),
    ] = False,
    uninstall: Annotated[
        bool,
        typer.Option(
            "--uninstall",
            help="Remove the skill from the target tool directories instead of installing.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing install at the target path.",
        ),
    ] = False,
    status: Annotated[
        bool,
        typer.Option(
            "--status",
            help="Print where the skill is currently installed and exit.",
        ),
    ] = False,
) -> None:
    """Install the LoreWiki agent skill into one or more AI tool directories.

    By default the command prints a numbered list of detected tools
    (the AI coding tools whose config root is already on this
    machine) and asks you to pick. The prompt accepts:

    \b
      - a single index  (``3``)
      - multiple indices (``1,3,5`` or ``1 3 5``)
      - a range         (``2-4``)
      - mixed forms     (``1,3-5,6``)
      - ``a`` to install into every detected tool
      - ``q`` (or empty) to quit without installing

    Pass ``--tool`` or ``--all`` to skip the prompt. ``--uninstall``
    reverses the operation; ``--force`` overwrites an existing
    install at the target path.
    """
    tool_ids = (
        [s.strip() for s in tool.split(",") if s.strip()]
        if tool is not None
        else None
    )
    rc = _run(
        tool_ids=tool_ids,
        install_all=all_,
        uninstall=uninstall,
        force=force,
        show_status=status,
    )
    if rc:
        raise typer.Exit(code=rc)

