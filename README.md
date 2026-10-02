# NOVA — Personal Autonomous AI Desktop System

KN Softic · Windows · local-first

Current status: **Phase 1 (Foundation)**. NOVA understands commands and replies in Roman Urdu, but does not
execute computer actions yet. See [LOGS.md](LOGS.md) for development history and approval status.

## Layout

```
nova/
├── backend/            Python FastAPI backend (127.0.0.1:8765)
│   ├── nova/
│   │   ├── main.py         REST API + WebSocket /ws
│   │   ├── orchestrator.py command → intent → response pipeline
│   │   ├── events.py       event types, NOVA states, event bus
│   │   ├── ai/             AI Provider Manager + rule-based provider
│   │   ├── language.py     Urdu / Hindi / Roman Urdu / English detection
│   │   ├── responses.py    Roman Urdu response catalog
│   │   ├── db.py           SQLite (settings, conversations, activity_log)
│   │   └── redaction.py    secret scrubbing before logging
│   └── tests/
├── desktop/            Electron + React + TypeScript + Tailwind
│   ├── electron/           main process, preload, backend launcher
│   └── src/                Command Center UI
├── data/               local database (created at runtime, git-ignored)
└── LOGS.md             human-readable development log (Roman Urdu)
```

## First-time setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

```bash
cd desktop
npm install
```

If `npm install` did not download the Electron binary (`desktop/node_modules/electron/dist` missing):

```bash
node node_modules/electron/install.js
```

## Run

Development (hot reload; Electron starts the backend automatically):

```bash
npm run dev
```

Production build:

```bash
npm start
```

(both from `desktop/`)

Backend alone: `backend\.venv\Scripts\python.exe -m nova` (from `backend/`).

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q
```

(from `backend/`)

```bash
npm run typecheck
```

(from `desktop/`)

## Configuration

Environment variables (backend):

| Variable | Default | Purpose |
| --- | --- | --- |
| `NOVA_HOST` | `127.0.0.1` | Bind address (keep loopback for the personal version) |
| `NOVA_PORT` | `8765` | Backend port |
| `NOVA_DATA_DIR` | `<repo>/data` | SQLite location |
| `NOVA_ASSISTANT_NAME` | `NOVA` | Assistant name |
| `NOVA_AI_PROVIDER` | `rule_based` | Active AI provider |

## Admin manual test (Phase 1)

1. `desktop/` mein `npm start` chalayein. NOVA window khulni chahiye aur upar "Backend connected" nazar aana chahiye.
2. Ye commands bhej kar dekhein:
   - `Hey NOVA, Chrome open karo` → intent `open_app`, jawab ke "abhi koi action nahi kiya gaya"
   - `کروم کھولو` → intent `open_app (ur)`
   - `mera system profile batao` → intent `system_info`
   - `Chrome mein web development search karo` → intent `web_search`
   - `Assalam-o-Alaikum` → salam ka jawab
3. Har command par avatar THINKING → COMPLETED → IDLE hona chahiye aur right panel mein events aane chahiye.
4. Window band karein — backend bhi band ho jana chahiye.
5. Sab theek ho to LOGS.md mein Admin Approval update karein, warna problem report karein.
