"""GET/POST /canfar/tutorials — git-backed tutorials hierarchy."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlparse, urlunparse

import tornado
from jupyter_server.base.handlers import APIHandler

CACHE_TTL_SECONDS = 8.0 * 60 * 60
DEFAULT_REPO = "https://github.com/rubin-dp0/tutorial-notebooks@prod"
DEFAULT_DEST = "notebooks/tutorials"


def _repo_spec() -> tuple[str, str]:
    raw = os.environ.get("CANFAR_TUTORIALS_REPO", DEFAULT_REPO).strip()
    if "@" not in raw:
        raw = f"{raw}@main"
    url, branch = raw.rsplit("@", 1)
    return url, branch or "main"


def _dest_root() -> Path:
    rel = os.environ.get("CANFAR_TUTORIALS_DEST", DEFAULT_DEST).lstrip("/")
    return Path.home() / rel


def _clone_repo(repo_url: str, branch: str, dirname: str) -> None:
    proc = subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            repo_url,
            "-b",
            branch,
            dirname,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"git clone {repo_url}@{branch} failed: {err}")


def _build_hierarchy_from(
    root: Path,
    *,
    clone_root: Path,
    parent: Path,
    repo_url: str,
    branch: str,
    dest_root: Path,
) -> dict[str, Any]:
    entries: dict[str, Any] | None = None
    subhierarchies: dict[str, Any] | None = None
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or entry.name == ".git":
            continue
        if entry.is_dir():
            child = _build_hierarchy_from(
                entry,
                clone_root=clone_root,
                parent=parent / entry.name,
                repo_url=repo_url,
                branch=branch,
                dest_root=dest_root,
            )
            if child.get("entries") or child.get("subhierarchies"):
                if subhierarchies is None:
                    subhierarchies = {}
                subhierarchies[entry.name] = child
            continue
        if not entry.name.endswith(".ipynb"):
            continue
        menu_name = entry.name[: -len(".ipynb")]
        rest = entry.relative_to(clone_root)
        src = urlunparse(
            urlparse(f"{repo_url}/raw/refs/heads/{branch}/{rest.as_posix()}")
        )
        dest = (dest_root / rest).relative_to(Path.home()).as_posix()
        if entries is None:
            entries = {}
        entries[menu_name] = {
            "menu_name": menu_name,
            "action": "fetch",
            "disposition": "prompt",
            "parent": parent.as_posix(),
            "src": src,
            "dest": dest,
        }
    return {"entries": entries, "subhierarchies": subhierarchies}


def _fetch_file(src: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(src, timeout=60) as resp:
        dest.write_bytes(resp.read())


class TutorialsHandler(APIHandler):
    def initialize(self, server_app=None) -> None:
        self.server_app = server_app
        if "canfar_tutorials" not in self.settings:
            self.settings["canfar_tutorials"] = {
                "timestamp": 0.0,
                "hierarchy": None,
            }
        self._cache = self.settings["canfar_tutorials"]

    def _cached_hierarchy(self) -> dict[str, Any] | None:
        stamp = float(self._cache.get("timestamp") or 0.0)
        if time.time() - stamp > CACHE_TTL_SECONDS:
            self._cache["timestamp"] = 0.0
            self._cache["hierarchy"] = None
            return None
        return self._cache.get("hierarchy")

    def _populate(self) -> dict[str, Any]:
        cached = self._cached_hierarchy()
        if cached is not None:
            return cached
        repo_url, branch = _repo_spec()
        dest_root = _dest_root()
        with TemporaryDirectory() as tmp:
            _clone_repo(repo_url, branch, tmp)
            hierarchy = _build_hierarchy_from(
                Path(tmp),
                clone_root=Path(tmp),
                parent=Path("/"),
                repo_url=repo_url,
                branch=branch,
                dest_root=dest_root,
            )
        self._cache["timestamp"] = time.time()
        self._cache["hierarchy"] = hierarchy
        return hierarchy

    @tornado.web.authenticated
    async def get(self) -> None:
        try:
            hierarchy = self._populate()
        except Exception as exc:
            self.set_status(500)
            self.finish(json.dumps({"error": str(exc)}))
            return
        self.finish(json.dumps(hierarchy))

    @tornado.web.authenticated
    async def post(self) -> None:
        try:
            body = json.loads(self.request.body.decode("utf-8"))
        except json.JSONDecodeError:
            self.set_status(400)
            self.finish(json.dumps({"error": "invalid JSON"}))
            return

        dest_rel = body.get("dest")
        src = body.get("src")
        disposition = body.get("disposition", "prompt")
        if not dest_rel or not src:
            self.set_status(400)
            self.finish(json.dumps({"error": "dest and src are required"}))
            return

        dest = Path.home() / str(dest_rel).lstrip("/")
        try:
            dest.resolve().relative_to(Path.home().resolve())
        except ValueError:
            self.set_status(400)
            self.finish(json.dumps({"error": "dest escapes home directory"}))
            return

        if dest.exists() and disposition == "prompt":
            self.set_status(409)
            self.finish(json.dumps({"error": "exists", "dest": dest_rel}))
            return
        if dest.exists() and disposition == "abort":
            self.set_status(204)
            return

        try:
            if body.get("action") == "copy" and Path(src).exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, dest)
            else:
                _fetch_file(str(src), dest)
        except Exception as exc:
            self.set_status(500)
            self.finish(json.dumps({"error": str(exc)}))
            return

        root = Path(self.settings.get("server_root_dir") or Path.home())
        try:
            guide = dest.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            guide = dest_rel
        self.finish(json.dumps({"dest": guide}))
