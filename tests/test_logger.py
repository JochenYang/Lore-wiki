"""Phase 0 logger tests.

Covers:
* env-var driven log level handling.
* optional ``LOREWIKI_LOG_FILE`` sink creation.
* idempotency of ``_configure`` so repeated ``get_logger`` calls do not
  duplicate sinks (which would multiply log output in real usage).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lorewiki.utils.logger import get_logger, reset_for_tests


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Each test starts with a clean logger configuration."""
    reset_for_tests()


def test_get_logger_returns_object_with_info_method() -> None:
    log = get_logger("unit-test")
    assert hasattr(log, "info")
    assert hasattr(log, "warning")
    assert hasattr(log, "error")


def test_get_logger_without_name_returns_root_logger() -> None:
    log = get_logger()
    assert log is not None
    log.info("smoke")


def test_log_level_env_var_is_respected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOREWIKI_LOG_LEVEL", "WARNING")
    log = get_logger("level-test")
    log.info("info-msg-should-be-filtered")
    log.warning("warning-msg-should-pass")
    captured = capsys.readouterr()
    combined = captured.err + captured.out
    assert "warning-msg-should-pass" in combined
    assert "info-msg-should-be-filtered" not in combined


def test_log_file_sink_writes_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "lorewiki.log"
    monkeypatch.setenv("LOREWIKI_LOG_FILE", str(log_file))
    monkeypatch.setenv("LOREWIKI_LOG_LEVEL", "INFO")
    log = get_logger("file-sink-test")
    log.info("hello-from-file-sink")
    # loguru's file sink uses ``enqueue=True``; flush by reconfiguring.
    reset_for_tests()
    assert log_file.exists()
    body = log_file.read_text(encoding="utf-8")
    assert "hello-from-file-sink" in body


def test_configure_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    log1 = get_logger("idem-1")
    log2 = get_logger("idem-2")
    log1.warning("only-once")
    captured = capsys.readouterr()
    combined = captured.err + captured.out
    # Should appear exactly once. Two add() calls would emit twice.
    assert combined.count("only-once") == 1
    # And the second logger still works.
    log2.warning("second-also-works")
    captured = capsys.readouterr()
    assert "second-also-works" in (captured.err + captured.out)
