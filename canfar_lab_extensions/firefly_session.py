"""Ensure a CANFAR Firefly session and return its connect URL."""

from __future__ import annotations

import json
import os
import platform
import random
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


DEFAULT_IMAGE = "images.canfar.net/skaha/firefly:2025.2"
DEFAULT_NAME = "firefly"
STATE_ENV = "CANFAR_FIREFLY_STATE"
ACTIVE_STATUSES = ("Running", "Pending")
DEAD_STATUSES = ("Terminating", "Succeeded", "Completed", "Error", "Failed")
POLL_SECONDS = 5.0
DEFAULT_TIMEOUT = 900.0
# Skaha counts these against the per-user interactive session limit.
UNCOUNTED_KINDS = ("headless", "desktop-app")
DEFAULT_PORTAL_URL = "https://www.canfar.net/science-portal/"


class FireflyLaunchError(RuntimeError):
    """Launch failure with user-facing guidance for the Lab tab."""

    def __init__(
        self, message: str, help_text: str | None = None, help_url: str | None = None
    ) -> None:
        super().__init__(message)
        self.help_text = help_text
        self.help_url = help_url


def portal_url() -> str:
    return os.environ.get("CANFAR_SCIENCE_PORTAL_URL", DEFAULT_PORTAL_URL)


def init_state_path() -> Path:
    """Export the per-server Firefly state path before any kernel is spawned.

    Kernels copy the server environment only at first launch (restarts reuse
    it), so the URL itself cannot be passed by env; the path to it can.
    """
    path = os.environ.get(STATE_ENV) or str(
        Path(tempfile.gettempdir()) / f"canfar-firefly-{os.getpid()}.json"
    )
    os.environ[STATE_ENV] = path
    return Path(path)


def write_state(page_config: dict[str, str]) -> Path | None:
    path = os.environ.get(STATE_ENV)
    if not path:
        return None
    target = Path(path)
    tmp = target.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(page_config), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        return None
    return target


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


def launch_timeout() -> float:
    try:
        return float(os.environ.get("CANFAR_FIREFLY_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def service_ready(url: str, timeout: float = 10.0) -> bool:
    """True once Firefly serves the loader script the Lab viewer fetches.

    The Skaha session reports Running well before Firefly inside it answers,
    so the session status alone is not enough to open the viewer.
    """
    probe = url.rstrip("/") + "/firefly_loader.js"
    try:
        with urllib.request.urlopen(probe, timeout=timeout) as resp:
            final_path = urllib.parse.urlparse(resp.geturl()).path
            return 200 <= resp.status < 300 and final_path.endswith("firefly_loader.js")
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _wait(deadline: float, what: str) -> None:
    if time.monotonic() + POLL_SECONDS > deadline:
        raise TimeoutError(
            f"Gave up after {int(launch_timeout())}s waiting for {what}. "
            "CANFAR may be busy; try again in a few minutes."
        )
    time.sleep(POLL_SECONDS)


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

    def active_session(self) -> dict[str, Any] | None:
        sessions = [
            s for s in self.session.fetch(kind="firefly")
            if s.get("status") in ACTIVE_STATUSES
        ]
        sessions.sort(key=lambda s: s.get("status") != "Running")
        return sessions[0] if sessions else None

    def create(self) -> dict[str, Any]:
        rejections: list[str] = []
        with self._capture_rejections(rejections):
            ids = self.session.create(name=self.name, image=self.image, kind="firefly")
        if not ids:
            raise self._create_error(rejections[-1] if rejections else None)
        return {"id": ids[0], "status": "Pending"}

    @contextmanager
    def _capture_rejections(self, sink: list[str]) -> Iterator[None]:
        """Collect CANFAR's error text; Session.create() only logs it and returns []."""

        def capture(response) -> None:
            if response.request.method == "POST" and response.status_code >= 400:
                response.read()
                sink.append(f"HTTP {response.status_code}: {response.text.strip()[:500]}")

        try:
            hooks = self.session.client.event_hooks["response"]
            hooks.insert(0, capture)
        except Exception:
            hooks = None
        try:
            yield
        finally:
            if hooks is not None and capture in hooks:
                hooks.remove(capture)

    def _interactive_sessions(self) -> list[dict[str, Any]]:
        try:
            sessions = self.session.fetch()
        except Exception:
            return []
        return [
            s for s in sessions
            if s.get("status") in ACTIVE_STATUSES and s.get("type") not in UNCOUNTED_KINDS
        ]

    def _create_error(self, rejection: str | None) -> FireflyLaunchError:
        active = self._interactive_sessions()
        listing = ", ".join(
            f"{s.get('type', '?')} '{s.get('name', s.get('id', '?'))}' ({s.get('status')})"
            for s in active
        )
        reason = rejection or "no reason was returned"
        message = f"CANFAR did not create a Firefly session: {reason}"
        at_limit = bool(rejection and "maximum" in rejection.lower())
        if at_limit or (rejection is None and active):
            help_text = (
                "CANFAR limits how many interactive sessions (notebook, desktop, "
                "CARTA, Firefly, …) you can run at once"
                + (f". You currently have {len(active)} active: {listing}." if active else ".")
                + " Delete a session you no longer need in the Science Portal, then press Retry."
            )
        else:
            help_text = f"Your active sessions: {listing}." if active else None
        return FireflyLaunchError(message, help_text=help_text, help_url=portal_url())

    def refresh(self, session_id: str) -> dict[str, Any]:
        info = self.session.info(session_id)
        return info[0] if info else {"id": session_id, "status": "Pending"}

    def wait_until_ready(self, progress: Callable[[str], None] = lambda _msg: None) -> str:
        """Create or reuse a session and block until Firefly answers; return its URL."""
        deadline = time.monotonic() + launch_timeout()
        progress("Looking for an existing Firefly session on CANFAR…")
        info = self.active_session()
        if info is None:
            progress("Requesting a new Firefly session from CANFAR…")
            info = self.create()
        while info.get("status") != "Running" or not info.get("connectURL"):
            status = info.get("status") or "Pending"
            if status in DEAD_STATUSES:
                raise RuntimeError(f"Firefly session {info['id']} is {status} on CANFAR")
            progress(f"CANFAR is scheduling Firefly session {info['id']} ({status})…")
            _wait(deadline, "CANFAR to start the Firefly session")
            info = self.refresh(info["id"])
        url = info["connectURL"]
        progress("Firefly session is running; waiting for the Firefly service to respond…")
        while not service_ready(url):
            _wait(deadline, f"Firefly to respond at {url}")
        self._url = url
        return url

    @property
    def url(self) -> str:
        if self._url is None:
            self.wait_until_ready()
        return self._url


_channel: str | None = None


def make_channel() -> str:
    """Return this server's Firefly channel.

    The Lab viewer binds its channel once per page load, so every ensure call
    must hand kernels the same channel or images go to a channel nobody shows.
    """
    global _channel
    if _channel is None:
        hostname = platform.node() or "canfar"
        _channel = f"ffChan-{hostname}-{int(time.time())}-{random.randint(1, 100)}"
    return _channel


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
    write_state(page_config)
    return page_config


class FireflyLauncher:
    """Start Firefly in the background and report progress for the Lab UI.

    CANFAR can take minutes to schedule a session, longer than a request
    should block, so POST starts (or joins) a launch and GET reports status.
    """

    def __init__(self, server_app=None) -> None:
        self.server_app = server_app
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = 0.0
        self._state: dict[str, Any] = {"status": "idle", "message": ""}

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            if state["status"] == "starting":
                state["elapsed"] = int(time.monotonic() - self._started)
            return state

    def start(self) -> dict[str, Any]:
        """Begin or join a launch. Blocks only to re-probe an already-ready Firefly."""
        with self._lock:
            busy = self._thread is not None and self._thread.is_alive()
            ready_url = self._state.get("fireflyURL") if self._state["status"] == "ready" else None
        if busy or (ready_url and service_ready(ready_url)):
            return self.status()
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._started = time.monotonic()
                self._state = {"status": "starting", "message": "Contacting CANFAR…"}
                self._thread = threading.Thread(
                    target=self._run, name="canfar-firefly-launch", daemon=True
                )
                self._thread.start()
        return self.status()

    def _log(self, message: str, *args: Any) -> None:
        log = getattr(self.server_app, "log", None)
        if log is not None:
            log.info("canfar_lab_extensions: " + message, *args)

    def _progress(self, message: str) -> None:
        with self._lock:
            self._state["message"] = message
        self._log("Firefly: %s", message)

    def _run(self) -> None:
        try:
            url = FireflySession().wait_until_ready(self._progress)
            config = inject_firefly_url(self.server_app, url, make_channel())
            state: dict[str, Any] = {"status": "ready", "message": "Firefly is ready", **config}
            self._log("Firefly ready at %s", url)
        except Exception as exc:
            state = {"status": "error", "message": str(exc) or exc.__class__.__name__}
            if isinstance(exc, FireflyLaunchError):
                state["help"] = exc.help_text
                state["helpURL"] = exc.help_url
            self._log("Firefly launch failed: %s", state["message"])
        with self._lock:
            self._state = state
