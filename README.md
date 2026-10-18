# Research Manuscript Workspace

A workspace for planning, writing, reviewing and packaging research manuscripts. It has a Next.js web app, a FastAPI
backend, and Temporal workers that run the research and writing tasks.

## What you need

| Tool | Version | Install (macOS) |
|---|---|---|
| Python | 3.13+ | `brew install python@3.13` |
| uv | recent | `brew install uv` |
| Node.js | 24 | `brew install node` |
| Temporal CLI | recent | `brew install temporal` |
| A PostgreSQL database with pgvector | 17+ | e.g. a free [Neon](https://neon.com) project |
| Claude CLI (optional) | recent | only for the "Claude login on this computer" AI option |

## First-time setup

### 1. Install dependencies

```bash
uv sync
cd apps/web && npm install && cd ../..
```

### 2. Create the `.env` file

```bash
cp .env.example .env
```

`.env` is git-ignored. It holds your database passwords, so never commit or share it.

### 3. Set up the database (Neon)

The app uses four database roles: an owner, plus three restricted roles that keep each user's data separate.

1. In the Neon console, copy the connection string for your project's owner role (e.g. `neondb_owner`).
2. Open Neon's SQL editor and run the following, giving each role **its own** strong password. Don't reuse the
   owner's password.
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   CREATE EXTENSION IF NOT EXISTS pgcrypto;
   CREATE ROLE rp_app    LOGIN PASSWORD '...' NOBYPASSRLS;
   CREATE ROLE rp_ingest LOGIN PASSWORD '...' NOBYPASSRLS;
   CREATE ROLE rp_system LOGIN PASSWORD '...' BYPASSRLS;
   ```
3. Fill in the four `RP_DATABASE_URL*` lines in `.env`. For each one:
   - use the **direct** host, the one without `-pooler` in its name;
   - change `postgresql://` to `postgresql+psycopg://`;
   - keep the whole value in quotes.

The tables are created automatically the first time you start the app.

### 4. Web app settings (optional)

To make the login page offer a demo account, create `apps/web/.env.local`:

```bash
NEXT_PUBLIC_DEMO_EMAIL="demo@example.com"
NEXT_PUBLIC_DEMO_PASSWORD="a-password-with-12+-chars-1"
```

Then register that account once at `/login`. The demo box appears in development only, never in a production build.

## Running the app

Use three terminals.

**Terminal 1: Temporal**

```bash
temporal server start-dev --namespace research-platform --db-filename ~/temporal.db
```

`--db-filename` keeps Temporal's data between restarts. You can watch workflows in the Temporal UI at
http://localhost:8233.

**Terminal 2: backend**

```bash
scripts/dev.sh up
```

This runs the database migrations, then starts the API (http://localhost:8000/v1/docs), the outbox relay, the
worker and the schedules. Logs are written to `var/log/`.

```bash
scripts/dev.sh status   # check what's running
scripts/dev.sh down     # stop everything
```

**Terminal 3: web app**

```bash
cd apps/web
PORT=3100 npm run dev
```

Open http://localhost:3100/login.

When you finish, run `scripts/dev.sh down`. While the backend runs, it keeps querying the database, so Neon can't go
idle and keeps using your free compute hours.

## Choosing the AI provider

Each project picks its AI provider in its settings:

- **Claude login on this computer:** uses the Claude CLI that is logged in on this machine. Run `claude`, then
  `/login`, once. This option is available only when the app runs locally.
- **My Anthropic API key:** connect your key under account settings. It is stored encrypted, and usage is billed to
  your Anthropic account.
- **Recorded test responses:** canned outputs for demos and tests. They are never available in production.

Projects that haven't picked a provider use the worker default (`RP_WORKER_MODEL_PROVIDER`, which is `fixture`
unless you set it).

## What doesn't work yet

- **LaTeX compiling and experiment runs.** They need a sandboxed container runtime that hasn't been chosen yet.
  Until then they report "sandbox unavailable", and the rest of the app works normally.
- **The backend test suites.** They expect a local PostgreSQL at `localhost:5433` with development passwords (see
  `apps/api/src/rp_api/testing.py`). Don't point them at Neon. The web unit tests (`cd apps/web && npm test`) need no
  database.

## Troubleshooting

| Problem | Fix |
|---|---|
| `PostgreSQL is not reachable` | Check the `RP_DATABASE_URL_OWNER` line in `.env`, and that the value is quoted. |
| `Namespace research-platform is not found` | Start Temporal with `--namespace research-platform` (see above), or run `temporal operator namespace create --namespace research-platform`, then `scripts/dev.sh down && scripts/dev.sh up`. |
| `EADDRINUSE` on port 3100 or 8000 | Another server is already using the port. Find it with `lsof -ti :3100` and stop it, or run `scripts/dev.sh down`. |
| Login fails for the demo account | The account doesn't exist in this database yet. Register it at `/login`. |

## Repository layout

```
apps/api            FastAPI backend (the only writer to the database)
apps/web            Next.js web app
services/research   Temporal workers, agents and the model gateway
workers/latex       LaTeX compile worker
workers/experiment  Experiment runner and validator
contracts           Shared data contracts
scripts             dev.sh (run locally), test_all.sh (backend tests)
```

## License

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE) for attribution, and
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for the libraries this project uses and their licenses.
