"""Tornado handlers for canfar_lab_extensions."""

from __future__ import annotations

from jupyter_server.utils import url_path_join

from .firefly import EnsureFireflyHandler
from .tutorials import TutorialsHandler


def setup_handlers(server_app) -> None:
    web_app = server_app.web_app
    base = web_app.settings["base_url"]
    host_pattern = ".*$"
    handlers = [
        (
            url_path_join(base, "canfar", "firefly", "ensure"),
            EnsureFireflyHandler,
            {"server_app": server_app},
        ),
        (
            url_path_join(base, "canfar", "tutorials"),
            TutorialsHandler,
            {"server_app": server_app},
        ),
    ]
    web_app.add_handlers(host_pattern, handlers)
