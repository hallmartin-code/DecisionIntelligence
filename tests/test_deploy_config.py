"""Guards on the deployment config.

A mistake here is invisible locally and only shows up as a failed healthcheck
on the platform, with no application traceback to explain it — so the rules
that keep the container able to boot are asserted rather than remembered.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAILWAY_JSON = ROOT / "railway.json"
PROCFILE = ROOT / "Procfile"


def railway_start_command() -> str:
    config = json.loads(RAILWAY_JSON.read_text(encoding="utf-8"))
    return config["deploy"]["startCommand"]


def procfile_start_command() -> str:
    line = PROCFILE.read_text(encoding="utf-8").strip()
    prefix, _, command = line.partition(":")
    assert prefix == "web", f"unexpected Procfile process type {prefix!r}"
    return command.strip()


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(railway_start_command(), id="railway.json"),
        pytest.param(procfile_start_command(), id="Procfile"),
    ],
)
class TestStartCommand:
    def test_port_has_a_default(self, command: str) -> None:
        """A bare $PORT vanishes when unset, silently eating the next flag.

        `--port $PORT --timeout-keep-alive 65` becomes `--port
        --timeout-keep-alive 65`; uvicorn rejects '--timeout-keep-alive' as a
        port number and exits before binding, leaving the platform to report
        nothing more useful than "service unavailable".
        """
        assert "${PORT:-" in command, (
            "Use ${PORT:-8000}, not $PORT — an unset PORT would consume the "
            "following flag as the port number and the app would never listen."
        )
        assert not re.search(r"--port\s+\$PORT\b", command)

    def test_binds_all_interfaces(self, command: str) -> None:
        """127.0.0.1 inside a container is unreachable from outside it."""
        assert "--host 0.0.0.0" in command

    def test_serves_the_app_from_src(self, command: str) -> None:
        assert "pitch_analyzer.web:app" in command
        assert "--app-dir src" in command


def test_both_start_commands_agree() -> None:
    """Railway reads railway.json and ignores the Procfile, so drift between
    them means a local run stops matching the deployed one."""
    assert railway_start_command() == procfile_start_command()


def test_healthcheck_targets_an_unauthenticated_route() -> None:
    from pitch_analyzer.web import app

    config = json.loads(RAILWAY_JSON.read_text(encoding="utf-8"))
    path = config["deploy"]["healthcheckPath"]
    route = next(r for r in app.routes if getattr(r, "path", None) == path)
    assert not route.dependant.dependencies, (
        f"{path} must stay free of auth — the platform probes it without "
        "credentials and a 401 reads as an unhealthy container."
    )


def test_healthcheck_timeout_allows_a_cold_start() -> None:
    """30s left no margin for a container that still has to boot."""
    config = json.loads(RAILWAY_JSON.read_text(encoding="utf-8"))
    assert config["deploy"]["healthcheckTimeout"] >= 120


def test_the_start_command_serves_healthz_with_port_unset() -> None:
    """End to end: run the real start command with PORT unset.

    The assertions above are a proxy for the failure; this reproduces it. The
    process has to bind and answer, not merely parse.
    """
    port = _free_port()
    # What `sh` substitutes for ${PORT:-8000} when PORT is unset, except that
    # the fallback becomes a free port so a busy 8000 cannot fail the test.
    args = [
        str(port) if part == "${PORT:-8000}" else part
        for part in shlex.split(railway_start_command())
    ]
    args[args.index("0.0.0.0")] = "127.0.0.1"
    assert args[0] == "uvicorn"
    argv = [sys.executable, "-m", *args]

    env = {k: v for k, v in os.environ.items() if k != "PORT"}
    env["ALLOW_ANONYMOUS"] = "1"
    # Popen as a context manager so the stdout pipe is closed on the way out;
    # left open it surfaces as an unraisable exception at finalization.
    with subprocess.Popen(
        argv,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ) as process:
        try:
            _wait_for_bind(process, port)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/healthz", timeout=10
            ) as response:
                assert json.loads(response.read())["status"] == "ok"
        finally:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover - shutdown hung
                process.kill()


def _wait_for_bind(process: subprocess.Popen, port: int, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            pytest.fail(f"the start command exited instead of serving:\n{output}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    pytest.fail(f"the app never bound port {port} within {timeout:.0f}s")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
