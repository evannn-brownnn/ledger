# Setup

Written for Windows + WSL2, since that is the primary environment. On
native Linux or macOS, skip sections 1 and 4 and read the Docker note in
section 2; everything else is identical. See "Native Linux" at the end for
the short version.

## 1 · WSL2

Develop inside WSL2, not Windows. Your production target is Linux, and
every hour spent debugging a Windows-only path issue teaches you nothing
transferable.

```powershell
wsl --install -d Ubuntu-24.04
```

**Keep the repo in the Linux filesystem.** `~/projects/ledger`, never
`/mnt/c/Users/...`. Cross-filesystem access through `/mnt/c` is dramatically
slower, and Python's many-small-files import behaviour plus Docker bind
mounts make it painful. This is the most common WSL performance mistake.

Cap WSL's memory so it cannot starve Windows. Create
`C:\Users\<you>\.wslconfig`:

```ini
[wsl2]
memory=16GB
processors=8
swap=8GB
```

Then `wsl --shutdown` and reopen.

## 2 · Docker

Install Docker Desktop for Windows and enable the WSL2 backend
(Settings → Resources → WSL Integration → enable your distro). Verify from
*inside* WSL:

```bash
docker run --rm hello-world
```

On native Linux, do not install Docker Desktop. Install Docker Engine plus
the Compose v2 plugin from Docker's own apt repository — the `docker.io`
package in Ubuntu's archive is older and has historically shipped without
`docker compose`. Then add yourself to the `docker` group and log out and
back in, or every `make` target needs `sudo`:

```bash
sudo usermod -aG docker "$USER"
```

## 3 · VS Code

Install the **WSL** extension, then from your WSL shell:

```bash
cd ~/projects/ledger && code .
```

The editor, terminal, debugger and Python interpreter all now run
Linux-side. On native Linux you skip the WSL extension and just open the
directory.

Extensions in use:

```bash
for e in ms-python.python ms-python.vscode-pylance ms-python.debugpy \
         ms-python.vscode-python-envs ms-azuretools.vscode-containers \
         ms-vscode.makefile-tools mhutchie.git-graph anthropic.claude-code; do
  code --install-extension "$e"
done
```

No Ruff extension: formatting and linting run through `make fmt` and
`make lint` in the container, so the pinned version is the only one that
ever touches the code. An editor extension resolving its own Ruff is how
you get a diff that CI disagrees with.

`.vscode/` is gitignored, so editor settings do not travel with the clone.
On a new machine, recreate `.vscode/settings.json`:

```json
{
    "makefile.configureOnOpen": false,
    "python.analysis.typeCheckingMode": "basic"
}
```

## 4 · Line endings

Windows line endings in shell scripts and Dockerfiles cause genuinely
baffling errors. The repo ships a `.gitattributes` that forces LF; also set:

```bash
git config --global core.autocrlf input
```

## 5 · Run it

```bash
cp .env.example .env
make up          # build and start db + api
make migrate     # apply migrations (no-op until you write models)
make test-unit   # should pass immediately
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Metrics: http://localhost:8000/metrics

`make help` lists everything.

## 6 · Local Python (optional but recommended)

The service runs in Docker, but your editor needs a local interpreter for
autocomplete and type checking.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv: fast, modern
uv venv && source .venv/bin/activate
uv pip install -r requirements-dev.lock
uv pip install -e . --no-deps
```

Point VS Code at `.venv/bin/python`.

Install from the lockfile, not from `".[dev]"`. `pyproject.toml` carries
lower bounds only, so resolving it directly gives you whatever is current
today — which is how your editor ends up type-checking against a different
mypy than CI runs. The lock is what CI and both Docker stages install, so
matching it is what makes local results mean anything.

After changing a dependency in `pyproject.toml`, regenerate both files and
commit them alongside the change:

```bash
make lock
```

## 7 · Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash
cd ~/projects/ledger && claude
```

The native installer needs no Node or npm. Run it from inside WSL, in the
repo root, so it operates on the same filesystem and git repo as everything
else.

Unlike `.vscode/`, `.claude/settings.json` is committed, so the plan-first
defaults follow the repo to every machine. `.claude/settings.local.json`
and `plans/` are gitignored and do not.

`CLAUDE.md` at the repo root is read automatically as standing instructions.
It defines which files are yours to hand-write, which are fair game for
assistance, and which invariants must never be violated. Edit it as the
project evolves — it is the main lever you have over how autonomously the
tool behaves.

Two habits worth forming:

- Ask for a plan before any non-trivial edit, and read it properly.
- Commit before letting it make a large change, so `git diff` is always a
  clean review surface.

## 8 · Native Linux, in short

Setting up a second machine that is not Windows. Sections 1 and 4 do not
apply; there is no `/mnt/c` to stay off, and `.gitattributes` already
forces LF.

Host software, with the versions this project is developed against:

| Tool | Version | Source |
| --- | --- | --- |
| Docker Engine + Compose v2 | 29.6 / v5.3 | Docker's apt repo, not Docker Desktop |
| GNU Make | 4.4 | `apt install make` |
| Git | 2.53 | `apt install git` |
| Python | 3.12 | matches `python:3.12-slim` in the Dockerfile |
| uv | 0.12 | `astral.sh/uv/install.sh` |
| VS Code | current | Microsoft `.deb` |
| Claude Code | current | `claude.ai/install.sh` |

Nothing else is needed on the host. In particular there is no `psql` and no
Node: `make psql` opens a shell in the database container, and Claude Code
uses the native installer.

Optional, install only if you want them:

- `pre-commit` (`uv tool install pre-commit && pre-commit install`) — the
  hooks shell out to `docker compose run`, so the dev image must exist
  first.
- Node and `@mermaid-js/mermaid-cli`, only to re-render the PNGs in
  `docs/diagrams/`. See `docs/DIAGRAMS.md`. Reading the diagrams needs
  neither: they render on GitHub, and in VS Code with a Markdown Preview
  Mermaid extension.

```bash
git clone https://github.com/evannn-brownnn/ledger.git && cd ledger
cp .env.example .env
make up && make migrate && make test-unit
```

Ports 5432, 5433 and 8000 must be free.

## Troubleshooting

**`docker: command not found` inside WSL** — WSL integration is not enabled
for this distro in Docker Desktop settings.

**Port 5432 already in use** — a Windows Postgres install is holding it.
Stop the Windows service, or change the host-side port in
`docker-compose.yml`. On native Linux the culprit is usually a distro
`postgresql` package: `sudo systemctl disable --now postgresql`.

**`permission denied` on the Docker socket (native Linux)** — you are not
in the `docker` group yet, or you have not logged out since being added.

**Painfully slow file operations** — the repo is on `/mnt/c`. Move it into
the Linux filesystem.

**`make: command not found`** — `sudo apt install make`.

**Tests skip with "test database unavailable"** — `make test` starts the
throwaway test database for you; plain `pytest` does not.
