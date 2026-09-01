"""Configuration read from the environment must never kill the container.

These values are typed by hand into a deployment dashboard. Parsing them with a
bare `int()` at import turns `50MB` into a process that exits before it can say
why, restarts, exits again, and surfaces only as a failed healthcheck — the
hardest possible way to find a one-character mistake.
"""

from __future__ import annotations

import importlib

import pytest

from pitch_analyzer import config


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Each test starts with no rejections recorded and no variables set."""
    monkeypatch.setattr(config, "_REJECTED", {})
    for name in (
        "MAX_UPLOAD_MB",
        "JOB_TTL_MINUTES",
        "MAX_CONCURRENT_ANALYSES",
        "USE_FILES_API",
    ):
        monkeypatch.delenv(name, raising=False)


def test_a_valid_value_is_used(monkeypatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "25")
    assert config.env_int("MAX_UPLOAD_MB", 50) == 25
    assert config.came_from_env("MAX_UPLOAD_MB")
    assert config.config_warnings() == []


def test_an_unset_value_uses_the_default() -> None:
    assert config.env_int("MAX_UPLOAD_MB", 50) == 50
    assert not config.came_from_env("MAX_UPLOAD_MB")


@pytest.mark.parametrize("bad", ["50MB", "50 MB", "fifty", "5.5", "", "   "])
def test_an_unparseable_value_falls_back_instead_of_raising(monkeypatch, bad) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", bad)
    assert config.env_int("MAX_UPLOAD_MB", 50) == 50


def test_a_rejected_value_is_reported_and_not_credited_to_the_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "50MB")
    config.env_int("MAX_UPLOAD_MB", 50)

    warnings = config.config_warnings()
    assert len(warnings) == 1
    assert "50MB" in warnings[0] and "50" in warnings[0]
    # It fell back to the default, so it must not claim to be configured.
    assert not config.came_from_env("MAX_UPLOAD_MB")


def test_warnings_are_ascii() -> None:
    """These go to a container log of unknown encoding; a UnicodeEncodeError
    while reporting a config problem would be a poor way to find out."""
    import os

    os.environ["MAX_UPLOAD_MB"] = "50MB"
    try:
        config.env_int("MAX_UPLOAD_MB", 50)
        for warning in config.config_warnings():
            warning.encode("ascii")
    finally:
        del os.environ["MAX_UPLOAD_MB"]


def test_a_value_below_the_minimum_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "0")
    assert config.env_int("MAX_CONCURRENT_ANALYSES", 2) == 2
    assert "minimum" in config.config_warnings()[0]


@pytest.mark.parametrize(
    "value,expected",
    [("0", False), ("false", False), ("no", False), ("off", False), ("OFF", False),
     ("1", True), ("true", True), ("anything", True), ("", True)],
)
def test_flags_parse(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("USE_FILES_API", value)
    assert config.env_flag("USE_FILES_API") is expected


def test_the_web_app_imports_with_every_setting_malformed(monkeypatch) -> None:
    """The regression: this used to raise ValueError at import and take the
    container down with it."""
    monkeypatch.setenv("MAX_UPLOAD_MB", "50MB")
    monkeypatch.setenv("JOB_TTL_MINUTES", "60m")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "two")
    monkeypatch.setenv("ALLOW_ANONYMOUS", "1")
    monkeypatch.setattr(config, "_REJECTED", {})

    from pitch_analyzer import web

    reloaded = importlib.reload(web)
    try:
        assert reloaded.MAX_UPLOAD_MB == reloaded.DEFAULT_MAX_UPLOAD_MB
        assert reloaded.JOB_TTL_MINUTES == 60
        assert reloaded.MAX_CONCURRENT_ANALYSES == 2
        assert not reloaded.UPLOAD_LIMIT_FROM_ENV

        from fastapi.testclient import TestClient

        with TestClient(reloaded.app) as client:
            body = client.get("/healthz").json()
        assert body["status"] == "ok"
        assert body["max_upload_mb"] == 50
        assert len(body["config_warnings"]) == 3
    finally:
        # Leave the module as the rest of the suite expects to find it.
        for name in ("MAX_UPLOAD_MB", "JOB_TTL_MINUTES", "MAX_CONCURRENT_ANALYSES"):
            monkeypatch.delenv(name, raising=False)
        config._REJECTED.clear()
        importlib.reload(web)
