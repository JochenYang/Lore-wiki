"""``lorewiki config ...`` sub-commands (list / get / set)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.table import Table

from lorewiki.cli.apps import config_app, console
from lorewiki.cli.helpers import (
    deep_merge,
    discover_project_dir,
    flatten_config,
    format_value,
    parse_toml_literal,
    resolve_config,
    safe_load_toml,
    unflatten,
)
from lorewiki.config import LoreWikiConfig, save_config


@config_app.command("list")
def config_list(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
) -> None:
    """List all configuration values."""
    cfg = resolve_config(path)
    table = Table(title="LoreWiki configuration", show_lines=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    for key, val in flatten_config(cfg).items():
        table.add_row(key, format_value(val, key=key))
    console.print(table)


@config_app.command("get")
def config_get(
    key: Annotated[str, typer.Argument(help="Config key to read (dotted, e.g. llm.backend).")],
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
) -> None:
    """Print a single configuration value."""
    cfg = resolve_config(path)
    flat = flatten_config(cfg)
    if key not in flat:
        console.print(f"[red]unknown key:[/red] {key}")
        raise typer.Exit(code=1)
    typer.echo(format_value(flat[key], key=key))


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Config key to write (dotted).")],
    value: Annotated[str, typer.Argument(help="New value (parsed as TOML literal).")],
    path: Annotated[
        str | None,
        typer.Option(
            "--path", "-p",
            help="Project / wiki path. Defaults to the discovered project config.",
        ),
    ] = None,
) -> None:
    """Update a configuration value and persist it to the project config file."""
    cfg = resolve_config(path)
    flat = flatten_config(cfg)
    if key not in flat:
        console.print(f"[red]unknown key:[/red] {key}")
        raise typer.Exit(code=1)
    parsed_value = parse_toml_literal(value)
    nested = unflatten({key: parsed_value})

    project_dir = (Path(path).expanduser().resolve() if path else discover_project_dir(cfg))
    target = project_dir / ".lorewiki" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)

    # Merge with whatever already lives in the project config file.
    existing = safe_load_toml(target) if target.exists() else {}
    merged = deep_merge(existing, nested)
    try:
        new_cfg = LoreWikiConfig(**merged)
    except ValidationError as exc:
        console.print(f"[red]invalid configuration:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    save_config(new_cfg, target)
    console.print(f"[green]set[/green] {key} = {parsed_value!r}  ->  {target}")


__all__ = ["config_get", "config_list", "config_set"]
