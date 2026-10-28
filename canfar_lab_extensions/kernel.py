"""IPython extension: sync Firefly URL/channel into the kernel environment.

lsst.display.firefly reads fireflyURLLab / FIREFLY_URL from os.environ, but the
URL only exists after the Lab launcher starts Firefly, which is usually after
the kernel was spawned. Before each cell, copy the state the server extension
wrote to $CANFAR_FIREFLY_STATE into os.environ.
"""

from __future__ import annotations

import json
import os

from .firefly_session import STATE_ENV

_ENV_KEYS = {
    "fireflyURL": ("FIREFLY_URL", "fireflyURLLab"),
    "fireflyChannel": ("fireflyChannelLab",),
    "fireflyLabExtension": ("fireflyLabExtension",),
}

_last_mtime: float | None = None


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
    # region agent log
    try:
        import time
        with open(os.path.expanduser("~/firefly-debug-674009.log"), "a") as _f: _f.write(json.dumps({"sessionId": "674009", "runId": "post-fix", "hypothesisId": "A,E", "location": "kernel.py:sync_firefly_env", "message": "kernel synced firefly env", "data": {"pid": os.getpid(), "state": path, "FIREFLY_URL": os.environ.get("FIREFLY_URL"), "fireflyURLLab": os.environ.get("fireflyURLLab"), "fireflyChannelLab": os.environ.get("fireflyChannelLab")}, "timestamp": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # endregion


def load_ipython_extension(ipython) -> None:
    # region agent log
    try:
        import sys, time
        with open(os.path.expanduser("~/firefly-debug-674009.log"), "a") as _f: _f.write(json.dumps({"sessionId": "674009", "runId": "post-fix", "hypothesisId": "A,E", "location": "kernel.py:load_ipython_extension", "message": "kernel extension loaded", "data": {"pid": os.getpid(), "state_env": os.environ.get(STATE_ENV), "prefix": sys.prefix, "FIREFLY_URL_at_load": os.environ.get("FIREFLY_URL")}, "timestamp": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # endregion
    sync_firefly_env()
    ipython.events.register("pre_run_cell", sync_firefly_env)


def unload_ipython_extension(ipython) -> None:
    try:
        ipython.events.unregister("pre_run_cell", sync_firefly_env)
    except ValueError:
        pass
