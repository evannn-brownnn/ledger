# Setup

Written for Windows + WSL2, since that is the target environment. On native
Linux or macOS, skip section 1.

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

## 3 · VS Code

Install the **WSL** extension, then from your WSL shell:

```bash
cd ~/projects/ledger && code .
```

The editor, terminal, debugger and Python interpreter all now run
Linux-side. Recommended extensions: Python, Ruff, Docker.

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
uv pip install -e ".[dev]"
```

Point VS Code at `.venv/bin/python`.

## 7 · Claude Code

```bash
npm install -g @anthropic-ai/claude-code
cd ~/projects/ledger && claude
```

Run it from inside WSL, in the repo root, so it operates on the same
filesystem and git repo as everything else.

`CLAUDE.md` at the repo root is read automatically as standing instructions.
It defines which files are yours to hand-write, which are fair game for
assistance, and which invariants must never be violated. Edit it as the
project evolves — it is the main lever you have over how autonomously the
tool behaves.

Two habits worth forming:

- Ask for a plan before any non-trivial edit, and read it properly.
- Commit before letting it make a large change, so `git diff` is always a
  clean review surface.

## Troubleshooting

**`docker: command not found` inside WSL** — WSL integration is not enabled
for this distro in Docker Desktop settings.

**Port 5432 already in use** — a Windows Postgres install is holding it.
Stop the Windows service, or change the host-side port in
`docker-compose.yml`.

**Painfully slow file operations** — the repo is on `/mnt/c`. Move it into
the Linux filesystem.

**`make: command not found`** — `sudo apt install make`.

**Tests skip with "test database unavailable"** — `make test` starts the
throwaway test database for you; plain `pytest` does not.
