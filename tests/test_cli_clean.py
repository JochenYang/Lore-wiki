"""Integration tests for the ``lorewiki clean`` CLI command."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lorewiki.cli import app

runner = CliRunner()


@pytest.fixture()
def wiki_with_dirty_files(tmp_path: Path) -> Path:
    """A wiki root with two .md files: one dirty, one already clean."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / ".lorewiki").mkdir()
    (wiki / ".lorewiki" / "config.toml").write_text(
        "retrieval_mode = \"bm25\"\n", encoding="utf-8"
    )
    (wiki / "api").mkdir()
    (wiki / "api" / "dirty.md").write_text(
        "---\n"
        'title: "#wx.dirty()"\n'
        "module: api\n"
        "---\n"
        "\n"
        "# [#](#wx-dirty) wx.dirty()\n"
        "\n"
        "> 基础库 1.1.0 开始支持\n"
        "\n"
        "body [link](../../bar.html)\n"
        "\n"
        "The translations are provided by WeChat Translation\n",
        encoding="utf-8",
    )
    (wiki / "api" / "clean.md").write_text(
        "---\n"
        'title: "wx.clean()"\n'
        "module: api\n"
        "---\n"
        "\n"
        "# wx.clean()\n"
        "\n"
        "body\n",
        encoding="utf-8",
    )
    return wiki


def test_cli_clean_dry_run_reports_changes_without_writing(
    wiki_with_dirty_files: Path,
) -> None:
    result = runner.invoke(
        app, ["clean", "--path", str(wiki_with_dirty_files), "--dry-run"]
    )
    assert result.exit_code == 0
    assert "Files scanned" in result.stdout
    # Dirty file is dirty, clean file is already clean
    assert "Changed" in result.stdout
    # The dry run does NOT modify files.
    dirty = (wiki_with_dirty_files / "api" / "dirty.md").read_text(encoding="utf-8")
    assert "The translations are provided" in dirty
    # And no backup dir is created.
    assert not (wiki_with_dirty_files / ".lorewiki" / "clean-backup").exists()


def test_cli_clean_writes_files_and_creates_backup(
    wiki_with_dirty_files: Path,
) -> None:
    result = runner.invoke(
        app, ["clean", "--path", str(wiki_with_dirty_files)]
    )
    assert result.exit_code == 0
    # Dirty file got cleaned in place.
    dirty = (wiki_with_dirty_files / "api" / "dirty.md").read_text(encoding="utf-8")
    assert "The translations are provided" not in dirty
    assert "基础库" not in dirty
    assert "[#](#" not in dirty
    # Frontmatter title hash removed.
    assert 'title: "wx.dirty()"' in dirty
    # Internal link .html stripped.
    assert "../../bar)" in dirty
    assert "../../bar.html)" not in dirty
    # Backup dir created with the original.
    backup_dir = wiki_with_dirty_files / ".lorewiki" / "clean-backup"
    assert backup_dir.exists()
    backups = list(backup_dir.rglob("*.md"))
    assert any(b.name == "dirty.md" for b in backups)
    backup = next(b for b in backups if b.name == "dirty.md")
    assert "The translations are provided" in backup.read_text(encoding="utf-8")


def test_cli_clean_is_idempotent_second_run_is_a_noop(
    wiki_with_dirty_files: Path,
) -> None:
    """Running clean twice leaves the file count the same and writes nothing."""
    runner.invoke(app, ["clean", "--path", str(wiki_with_dirty_files)])
    first_size = (wiki_with_dirty_files / "api" / "dirty.md").stat().st_size
    # Second run: nothing should change.
    result2 = runner.invoke(app, ["clean", "--path", str(wiki_with_dirty_files)])
    assert result2.exit_code == 0
    second_size = (wiki_with_dirty_files / "api" / "dirty.md").stat().st_size
    assert first_size == second_size


def test_cli_clean_no_backup_skips_backup_dir(
    wiki_with_dirty_files: Path,
) -> None:
    result = runner.invoke(
        app,
        ["clean", "--path", str(wiki_with_dirty_files), "--no-backup"],
    )
    assert result.exit_code == 0
    assert not (wiki_with_dirty_files / ".lorewiki" / "clean-backup").exists()
    # But the file still got cleaned.
    dirty = (wiki_with_dirty_files / "api" / "dirty.md").read_text(encoding="utf-8")
    assert "The translations are provided" not in dirty


def test_cli_clean_unknown_path_errors(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["clean", "--path", str(tmp_path / "does-not-exist")]
    )
    assert result.exit_code != 0
