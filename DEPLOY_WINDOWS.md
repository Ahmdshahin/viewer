# MapViewer — Windows dev-server deployment

Single-port production layout: the FastAPI backend serves the API **and**
the built frontend (`frontend/dist`) on `0.0.0.0:8000`. No Node.js needed
at runtime — only Python + PostgreSQL.

## 0. What you need in hand

| Item | Notes |
|---|---|
| Postgres backup with the 10k requests | `.dump`/`.backup` (pg_restore) or `.sql` (psql). Must include schema + PostGIS data. Verify it first: restore to a scratch DB and check `SELECT count(*) FROM requests;` |
| `Unified_Database.gpkg` (+ `Point_Database.gpkg` if used) | Tiny files; copy next to the repo or set `GPKG_PATH` to their location |
| Postgres superuser password on the new machine | `setup_dev_server.bat` takes it as 2nd arg |
| Git access to `git@github.com:Ahmdshahin/viewer.git` | Or HTTPS + token |

> Current machine state (Oct 2026): the local `requests`/`mudryia_requests`
> tables are **empty** (geometry + users intact). Do **not** dump this
> machine's DB as the data source — use your external backup.

## 1. Install prerequisites (new server)

- Python **3.10** (`python --version`), check "Add to PATH"
- Node.js **20+** (build only): `node --version`
- PostgreSQL **16** + PostGIS **3.5** (Stack Builder → Spatial Extensions);
  remember the `postgres` password
- Git

## 2. Get the code and data files

```bat
git clone git@github.com:Ahmdshahin/viewer.git MapViewer
cd MapViewer
git log --oneline -3        :: HEAD must include all recent work, tree clean
```

Copy next to the repo root: your `*.backup`/`*.sql` dump and the `.gpkg`
files (or note their path for `GPKG_PATH`).

## 3. One-command setup (Administrator shell, repo root)

```bat
setup_dev_server.bat D:\backups\Taqnen_data.dump <db_password>
```

It creates `venv/`, installs requirements, builds the frontend, creates
`Taqnen_data`, enables PostGIS, restores the backup, and seeds
`admin/admin123` if missing.

Environment overrides (optional, else defaults `localhost:5432/postgres`):

| Var | Default | Purpose |
|---|---|---|
| `GEOPORTAL_DB_HOST/PORT/USER/PASSWORD/NAME` | `localhost/5432/postgres/Taqnen_data` | DB connection |
| `GPKG_PATH` | `<repo>\Unified_Database.gpkg` | fallback geometry source |
| `SECRET_KEY` | insecure default — **must change** | JWT signing (changing it logs everyone out) |

Persist them with `setx VAR "value"` (new shell picks them up).

## 4. Start and verify

```bat
run_geoportal_prod.bat     :: serves API + web on 0.0.0.0:8000
```

Open `http://SERVER-IP:8000` → login `admin/admin123` → **change the
password** → verify:

1. `/requests` total ≈ 10,612 and `/mudryia-requests` ≈ 4,015
2. Map tiles load (PostGIS reachable)
3. Export CSV downloads
4. `http://SERVER-IP:8000/docs` responds (API healthy)
5. Windows Firewall allows inbound TCP 8000 (script does not open it)

## 5. Notes / pitfalls

- `backend/db_connection.json` is gitignored on purpose (holds a password);
  the setup uses env vars / CLI args instead — never commit it.
- `frontend/dist/` is gitignored and rebuilt by setup; never copy it.
- Keep only **one** Postgres version listening on 5432 (this machine
  accidentally ran 16 + 18 side by side).
- `seed_admin.py` is idempotent — safe to re-run.
- Dev mode (optional): `run_geoportal.bat` starts uvicorn on
  127.0.0.1:8000 + `npm run dev` on :5173 (Vite proxies `/api`).
