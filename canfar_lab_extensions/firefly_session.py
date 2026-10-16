"""Ensure a CANFAR Firefly session and return its connect URL."""

from __future__ import annotations

import os
import platform
import random
import time
from pathlib import Path
from typing import Any


DEFAULT_IMAGE = "images.canfar.net/skaha/firefly:2025.2"
DEFAULT_NAME = "firefly"


def _import_session():
    try:
        from canfar.sessions import Session
    except Exception as ex:
        if ex.__class__.__name__ == "ConfigResetRequiredError":
            config_file = Path.home() / ".canfar" / "config.yaml"
            if config_file.exists():
                config_file.unlink()
            from canfar.sessions import Session
        else:
            raise
    return Session


class FireflySession:
    """Create or reuse a Skaha Firefly session."""

    def __init__(
        self,
        *,
        name: str | None = None,
        image: str | None = None,
    ) -> None:
        self.name = name or os.environ.get("CANFAR_FIREFLY_NAME", DEFAULT_NAME)
        self.image = image or os.environ.get("CANFAR_FIREFLY_IMAGE", DEFAULT_IMAGE)
        self.session = _import_session()()
        self._url: str | None = None
        self._info: dict[str, Any] | None = None

    @property
    def session_info(self) -> dict[str, Any]:
        if self._info is not None:
            return self._info
        session_list = self.session.fetch("firefly")
        if len(session_list) == 0:
            self._launch()
            session_list = self.session.fetch("firefly")
        if not session_list:
            raise RuntimeError("Firefly session was created but fetch returned empty")
        self._info = session_list[0]
        return self._info

    def _launch(self) -> None:
        self.session.create(
            name=self.name,
            image=self.image,
            kind="firefly",
        )

    @property
    def url(self) -> str:
        if self._url is None:
            self._url = self.session_info["connectURL"]
        return self._url


def make_channel() -> str:
    hostname = platform.node() or "canfar"
    return f"ffChan-{hostname}-{int(time.time())}-{random.randint(1, 100)}"


def write_jupyter_firefly_config(url: str) -> Path | None:
    """Persist c.Firefly.url for the next Lab start."""
    config_dir = Path(
        os.environ.get("JUPYTER_CONFIG_DIR")
        or (Path.home() / ".jupyter")
    )
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "jupyter_config.py"
        line = f"c.Firefly.url = {url!r}\n"
        existing = ""
        if config_path.exists():
            existing = config_path.read_text(encoding="utf-8")
        if "c.Firefly.url" in existing:
            lines = []
            for raw in existing.splitlines(keepends=True):
                if raw.lstrip().startswith("c.Firefly.url"):
                    lines.append(line if line.endswith("\n") else line + "\n")
                else:
                    lines.append(raw)
            config_path.write_text("".join(lines), encoding="utf-8")
        else:
            with config_path.open("a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(line)
        return config_path
    except OSError:
        return None


def inject_firefly_url(server_app, url: str, channel: str) -> dict[str, str]:
    """Update running Jupyter process Firefly settings and return config dict."""
    os.environ["FIREFLY_URL"] = url
    os.environ["fireflyURLLab"] = url
    os.environ["fireflyChannelLab"] = channel
    os.environ["fireflyLabExtension"] = "true"

    page_config = {
        "fireflyLabExtension": "true",
        "fireflyURL": url,
        "fireflyHtmlFile": "",
        "fireflyChannel": channel,
    }

    web_app = getattr(server_app, "web_app", None)
    if web_app is not None:
        web_app.settings["fireflyURL"] = url
        web_app.settings["fireflyHtmlFile"] = ""
        web_app.settings["canfarFireflyConfig"] = page_config

    try:
        import jupyter_firefly_extensions.handlers as ff_handlers

        ff_handlers.firefly_config = dict(page_config)
    except Exception:
        pass

    write_jupyter_firefly_config(url)
    return page_config


def ensure_firefly(server_app=None) -> dict[str, str]:
    """Ensure Firefly is running and inject URL; return fireflyURL/channel."""
    ff = FireflySession()
    url = ff.url
    channel = make_channel()
    if server_app is not None:
        return inject_firefly_url(server_app, url, channel)
    write_jupyter_firefly_config(url)
    return {
        "fireflyLabExtension": "true",
        "fireflyURL": url,
        "fireflyHtmlFile": "",
        "fireflyChannel": channel,
    }
