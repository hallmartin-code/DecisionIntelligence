"""Reading configuration out of the environment, survivably.

Every one of these values is set by hand in a deployment dashboard, where a
plausible-looking typo — `50MB`, `60m`, `two` — is easy to make. Parsing them
with a bare `int()` at import time turns that typo into a container that dies
before it logs anything the reader can act on, restarts, and dies again; the
platform reports only a failed healthcheck. A misconfigured value should cost
the setting, not the service.

So a bad value falls back to the default and records a warning, which the web
app logs at startup and reports on `/healthz`.
"""

from __future__ import annotations

import os

#: Names whose environment value could not be used, mapped to the reason.
#: Populated at import time by the module reading its configuration.
_REJECTED: dict[str, str] = {}


def env_flag(name: str, default: bool = True) -> bool:
    """An on/off switch. Anything unparseable reads as on, like the default."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def env_int(name: str, default: int, minimum: int = 1) -> int:
    """A whole number, falling back to `default` rather than raising."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default

    try:
        value = int(raw)
    except ValueError:
        _REJECTED[name] = (
            f"{name}={raw!r} is not a whole number - using {default} instead."
        )
        return default

    if value < minimum:
        _REJECTED[name] = (
            f"{name}={value} is below the minimum of {minimum} - "
            f"using {default} instead."
        )
        return default

    return value


def came_from_env(name: str) -> bool:
    """True when the environment actually supplied the value in use."""
    return bool(os.environ.get(name, "").strip()) and name not in _REJECTED


def config_warnings() -> list[str]:
    """Every environment value that had to be rejected, in name order."""
    return [_REJECTED[name] for name in sorted(_REJECTED)]
