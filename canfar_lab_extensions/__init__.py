"""CANFAR JupyterLab extensions: Firefly launcher and Tutorials menu."""

from __future__ import annotations

from pathlib import Path

from ._version import __version__

__all__ = ["__version__", "_jupyter_labextension_paths", "_jupyter_server_extension_points"]


def _jupyter_labextension_paths() -> list[dict[str, str]]:
    return [{"src": "labextension", "dest": "canfar_lab_extensions"}]


def _jupyter_server_extension_points() -> list[dict[str, str]]:
    return [{"module": "canfar_lab_extensions"}]


def _load_jupyter_server_extension(server_app) -> None:
    from .handlers import setup_handlers

    setup_handlers(server_app)
    server_app.log.info("Registered canfar_lab_extensions server extension")


# Jupyter Server < 2 compatibility name
load_jupyter_server_extension = _load_jupyter_server_extension


def _get_labextension_dir() -> Path:
    return Path(__file__).parent / "labextension"
