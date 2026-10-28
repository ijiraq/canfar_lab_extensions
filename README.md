# canfar_lab_extensions

JupyterLab server + frontend extension that brings the RSP notebook experience
to CANFAR sciplat sessions:

- **Firefly Viewer** launcher card: ensures a CANFAR (Skaha) Firefly session
  exists and opens Firefly in a Lab tab via the Firefly JS API. The tab opens
  immediately with launch progress and loads the viewer once Firefly answers.
  Nothing is started until the user clicks.
- **Kernel Firefly sync** (IPython extension `canfar_lab_extensions.kernel`):
  copies the Firefly URL/channel into each kernel's environment before every
  cell, so `lsst.display.firefly` works in kernels started (or restarted)
  before Firefly was launched. Enable it with
  `c.InteractiveShellApp.extensions.append("canfar_lab_extensions.kernel")`
  in `<env>/etc/ipython/ipython_kernel_config.py`.
- **Tutorials** menu: shallow-clones a configurable git repository on first use
  and lists its notebooks for one-click opening under `$HOME`.

The wheel ships a **prebuilt** labextension, so consumers never need Node,
`jlpm`, or a JupyterLab rebuild.

## Install

Install into the Python environment whose `jupyter` actually serves the Lab
session. On the CANFAR sciplat-lab image that is the `lsst-scipipe` conda env
(the one `loadLSST.bash` activates), not the separate
`/usr/local/share/jupyterlab/venv` the upstream RSP uses. From a GitHub
Release:

```bash
V=0.1.2
pip install "https://github.com/ijiraq/canfar_lab_extensions/releases/download/v${V}/canfar_lab_extensions-${V}-py3-none-any.whl"
```

Or with uv, targeting a specific interpreter:

```bash
uv pip install --python /path/to/env/bin/python \
  "https://github.com/ijiraq/canfar_lab_extensions/releases/download/v${V}/canfar_lab_extensions-${V}-py3-none-any.whl"
```

Both the server extension and the labextension are enabled automatically on
install. Verify with:

```bash
jupyter server extension list
jupyter labextension list
```

If `jupyter_firefly_extensions` is also installed in that environment, disable
its launcher so only the CANFAR card appears:

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
| `CANFAR_FIREFLY_TIMEOUT` | `900` | Seconds to wait for the session and the Firefly service before giving up |

## Server API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/canfar/firefly/ensure` | Start (or join) a background Firefly launch; returns its status |
| `GET` | `/canfar/firefly/ensure` | Launch status: `{status: idle\|starting\|ready\|error, message, elapsed?, fireflyURL?, fireflyChannel?}` |
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
