"""IPython extension: sync Firefly URL/channel into the kernel environment.

lsst.display.firefly reads fireflyURLLab / FIREFLY_URL from os.environ, but the
URL only exists after the Lab launcher starts Firefly, which is usually after
the kernel was spawned. Before each cell, copy the state the server extension
wrote to $CANFAR_FIREFLY_STATE into os.environ.

If Firefly is relaunched at a new URL (e.g. the user deleted the old session
from the Science Portal), also drop lsst.display.firefly's cached client so the
next Display() connects to the new instance.
"""

from __future__ import annotations

import json
import os
import sys

from .firefly_session import STATE_ENV

_ENV_KEYS = {
    "fireflyURL": ("FIREFLY_URL", "fireflyURLLab"),
    "fireflyChannel": ("fireflyChannelLab",),
    "fireflyLabExtension": ("fireflyLabExtension",),
}

_last_mtime: float | None = None


def _drop_stale_display_client(url: str) -> None:
    # display_firefly builds its module-level client on the first Display()
    # and never rebuilds it, even after _close().
    ff = sys.modules.get("lsst.display.firefly.firefly")
    client = getattr(ff, "_fireflyClient", None)
    if client is None or str(getattr(client, "url", "")).rstrip("/") == url.rstrip("/"):
        return
    for close in (
        getattr(client, "disconnect", None),
        getattr(getattr(client, "session", None), "close", None),
    ):
        try:
            if close is not None:
                close()
        except Exception:
            pass
    ff._fireflyClient = None
    print(
        "Firefly was restarted at a new address; create a new Display "
        "(existing Display objects still point at the old one)."
    )


def sync_firefly_env(*_args) -> None:
    global _last_mtime
    path = os.environ.get(STATE_ENV)
    if not path:
        return
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return
    if mtime == _last_mtime:
        return
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return
    for key, env_names in _ENV_KEYS.items():
        value = state.get(key)
        if value:
            for name in env_names:
                os.environ[name] = value
    _last_mtime = mtime
    if state.get("fireflyURL"):
        _drop_stale_display_client(state["fireflyURL"])


def load_ipython_extension(ipython) -> None:
    sync_firefly_env()
    ipython.events.register("pre_run_cell", sync_firefly_env)


def unload_ipython_extension(ipython) -> None:
    try:
        ipython.events.unregister("pre_run_cell", sync_firefly_env)
    except ValueError:
        pass
