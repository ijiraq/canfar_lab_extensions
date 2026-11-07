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
from typing import Any, NamedTuple
from urllib.parse import urlparse, urlunparse

import tornado
from jupyter_server.base.handlers import APIHandler

CACHE_TTL_SECONDS = 8.0 * 60 * 60
DEFAULT_REPO = "https://github.com/rubin-dp0/tutorial-notebooks@prod"
DEFAULT_DEST = "notebooks/tutorials"


class RepoSpec(NamedTuple):
    """One CANFAR_TUTORIALS_REPO item: ``[Label=]url[@branch][#subdir]``."""

    label: str
    url: str
    branch: str
    subdir: str


def _parse_repo_spec(item: str) -> RepoSpec:
    label = ""
    scheme, sep, _ = item.partition("://")
    if sep and "=" in scheme:
        label, item = item.split("=", 1)
    item, _, subdir = item.partition("#")
    url, at, branch = item.rpartition("@")
    # No branch given, or the "@" belongs to the URL (git@host:org/repo).
    if not at or "/" in branch or ":" in branch:
        url, branch = item, ""
    return RepoSpec(
        label=label.strip().strip("/"),
        url=url,
        branch=branch or "main",
        subdir=subdir.strip("/"),
    )


def _repo_specs() -> list[RepoSpec]:
    """Parse CANFAR_TUTORIALS_REPO, a whitespace- or comma-separated list."""
    raw = os.environ.get("CANFAR_TUTORIALS_REPO", DEFAULT_REPO)
    return [_parse_repo_spec(item) for item in raw.replace(",", " ").split()]


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
        # A missing or private repo must fail, not wait for credentials.
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"git clone {repo_url}@{branch} failed: {err}")


def _build_hierarchy_from(
    root: Path,
    *,
    clone_root: Path,
    menu_root: Path,
    parent: Path,
    repo_url: str,
    branch: str,
    dest_root: Path,
) -> dict[str, Any]:
    """Menu for ``root``. Download URLs are relative to ``clone_root``;
    saved copies are relative to ``menu_root`` under ``dest_root``."""
    entries: dict[str, Any] | None = None
    subhierarchies: dict[str, Any] | None = None
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or entry.name == ".git":
            continue
        if entry.is_dir():
            child = _build_hierarchy_from(
                entry,
                clone_root=clone_root,
                menu_root=menu_root,
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
        dest = (dest_root / entry.relative_to(menu_root)).relative_to(Path.home()).as_posix()
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


def _spec_hierarchy(spec: RepoSpec, clone: Path, dest_root: Path) -> dict[str, Any]:
    """Menu for one spec, wrapped in a ``spec.label`` submenu if labelled."""
    root = clone / spec.subdir if spec.subdir else clone
    if not root.resolve().is_relative_to(clone.resolve()) or not root.is_dir():
        raise FileNotFoundError(f"no folder {spec.subdir!r} in {spec.url}@{spec.branch}")
    parent = Path("/") / spec.label if spec.label else Path("/")
    hierarchy = _build_hierarchy_from(
        root,
        clone_root=clone,
        menu_root=root,
        parent=parent,
        repo_url=spec.url,
        branch=spec.branch,
        dest_root=dest_root / spec.label if spec.label else dest_root,
    )
    if spec.label and (hierarchy["entries"] or hierarchy["subhierarchies"]):
        return {"entries": None, "subhierarchies": {spec.label: hierarchy}}
    return hierarchy


def _merge_hierarchy(into: dict[str, Any], other: dict[str, Any]) -> None:
    """Merge ``other`` into ``into``; same-name submenus merge, later entries win."""
    if other.get("entries"):
        into["entries"] = {**(into.get("entries") or {}), **other["entries"]}
    for name, sub in (other.get("subhierarchies") or {}).items():
        subs = into.get("subhierarchies") or {}
        into["subhierarchies"] = subs
        if name in subs:
            _merge_hierarchy(subs[name], sub)
        else:
            subs[name] = sub


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
        specs = _repo_specs()
        dest_root = _dest_root()
        hierarchy: dict[str, Any] = {"entries": None, "subhierarchies": None}
        errors: list[str] = []
        with TemporaryDirectory() as tmp:
            clones: dict[tuple[str, str], Path | Exception] = {}
            for spec in specs:
                key = (spec.url, spec.branch)
                if key not in clones:
                    path = Path(tmp) / str(len(clones))
                    try:
                        _clone_repo(spec.url, spec.branch, str(path))
                        clones[key] = path
                    except Exception as exc:
                        clones[key] = exc
                try:
                    clone = clones[key]
                    if isinstance(clone, Exception):
                        raise clone
                    _merge_hierarchy(hierarchy, _spec_hierarchy(spec, clone, dest_root))
                except Exception as exc:
                    errors.append(str(exc))
                    self.log.warning("canfar tutorials: skipping %s: %s", spec, exc)
        if errors and len(errors) == len(specs):
            raise RuntimeError("; ".join(errors))
        # Retry a partly failed menu on the next request instead of caching it.
        if not errors:
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
