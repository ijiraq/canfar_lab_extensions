# canfar_lab_extensions

JupyterLab server + frontend extension that brings the RSP notebook experience
to CANFAR sciplat sessions:

- **Firefly Viewer** launcher card: ensures a CANFAR (Skaha) Firefly session
  exists, injects its URL into the running Jupyter server, and opens Firefly in
  a Lab tab via the Firefly JS API. Nothing is started until the user clicks.
- **Tutorials** menu: shallow-clones a configurable git repository on first use
  and lists its notebooks for one-click opening under `$HOME`.

The wheel ships a **prebuilt** labextension, so consumers never need Node,
`jlpm`, or a JupyterLab rebuild.

## Install

Install into the environment that runs JupyterLab (on sciplat-lab that is the
Lab venv, not the LSST stack environment). From a GitHub Release:

```bash
V=0.1.0
pip install "https://github.com/ijiraq/canfar_lab_extensions/releases/download/v${V}/canfar_lab_extensions-${V}-py3-none-any.whl"
```

Or with uv, targeting a specific interpreter:

```bash
uv pip install --python /usr/local/share/jupyterlab/venv/bin/python \
  "https://github.com/ijiraq/canfar_lab_extensions/releases/download/v${V}/canfar_lab_extensions-${V}-py3-none-any.whl"
```

Both the server extension and the labextension are enabled automatically on
install. Verify with:

```bash
jupyter server extension list
jupyter labextension list
```

The stock `jupyter_firefly_extensions` launcher should be disabled so only the
CANFAR card appears:

```bash
jupyter labextension disable jupyter_firefly_extensions
```

PyPI publishing will follow once the package is stable.

## Configuration

All settings are environment variables read by the Jupyter server process, so
deployments can override them without rebuilding.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CANFAR_TUTORIALS_REPO` | `https://github.com/rubin-dp0/tutorial-notebooks@prod` | `url@branch` of the tutorials repository |
| `CANFAR_TUTORIALS_DEST` | `notebooks/tutorials` | Clone destination, relative to `$HOME` |
| `CANFAR_FIREFLY_IMAGE` | `images.canfar.net/skaha/firefly:2025.2` | Image for the Firefly Skaha session |
| `CANFAR_FIREFLY_NAME` | `firefly` | Skaha session name to create/reuse |

## Server API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/canfar/firefly/ensure` | Create or reuse the Firefly session; returns `{fireflyURL, fireflyChannel, ...}` |
| `GET` | `/canfar/tutorials` | Ensure the tutorials clone and list notebooks |

## Development

Requires Node 20+, Python 3.10+, and `jupyterlab>=4,<5`.

```bash
python -m venv .venv && . .venv/bin/activate
pip install "jupyterlab>=4,<5" hatchling hatch-jupyter-builder build
jlpm install
jlpm run build:prod      # or `jlpm watch` during development
pip install -e .
jupyter labextension develop . --overwrite
jupyter server extension enable canfar_lab_extensions
```

Yarn's `node-modules` linker is pinned in `.yarnrc.yml`; PnP breaks
`hatch-jupyter-builder` inside pip's isolated build environment.

### Release

1. Bump `version` in both `pyproject.toml` and `package.json`
   (and `canfar_lab_extensions/_version.py`).
2. Commit, then tag and push:

   ```bash
   git tag v0.1.0 && git push origin main v0.1.0
   ```

The `Release` workflow verifies the tag matches the package version, builds the
wheel and sdist, smoke-tests the install, and attaches the artifacts to a
GitHub Release.

## License

AGPL-3.0-or-later. See `LICENSE`.
