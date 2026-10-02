# NOVA — Personal Autonomous AI Desktop System

KN Softic · Windows · local-first

Current status: **Phase 3 (NOVA UI)**. NOVA understands commands, replies in Roman Urdu, scans the PC and answers
system questions. The Command Center has a state-aware avatar, live mic meter, settings (name, wake word,
listening, startup mode) and a persisted activity log. It does not launch apps, recognise speech, or change
anything on the PC yet. See [LOGS.md](LOGS.md) for development history and approval status.

## Layout

```
nova/
├── backend/            Python FastAPI backend (127.0.0.1:8765)
│   ├── nova/
│   │   ├── main.py         REST API + WebSocket /ws
│   │   ├── orchestrator.py command → intent → agent → response pipeline
│   │   ├── discovery/      system scan: probe.ps1, Windows collectors, app catalog, self-configuration
│   │   ├── agents/         System Agent (read-only)
│   │   ├── events.py       event types, NOVA states, event bus
│   │   ├── ai/             AI Provider Manager + rule-based provider
│   │   ├── language.py     Urdu / Hindi / Roman Urdu / English detection
│   │   ├── responses.py    Roman Urdu response catalog
│   │   ├── user_settings.py assistant name, wake word, listening, startup mode
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

```bash
npm test
```

(both from `desktop/`)

## Configuration

Environment variables (backend):

| Variable | Default | Purpose |
| --- | --- | --- |
| `NOVA_HOST` | `127.0.0.1` | Bind address (keep loopback for the personal version) |
| `NOVA_PORT` | `8765` | Backend port |
| `NOVA_DATA_DIR` | `<repo>/data` | SQLite location |
| `NOVA_ASSISTANT_NAME` | `NOVA` | Assistant name |
| `NOVA_AI_PROVIDER` | `rule_based` | Active AI provider |
| `NOVA_DISCOVERY_ON_STARTUP` | `1` | Rescan the system in the background on every start |

## Admin manual test (Phase 3)

1. `desktop/` mein `npm start` chalayein. Upar status bar mein live CPU/RAM, "Mic: Off", "Backend connected" aur **⚙ Settings** nazar aana chahiye.
2. **Mic** button dabayein. "Mic: On" (hara) hona chahiye, button ke sath waveform chalni chahiye, aur bolne par avatar ka gola awaaz ke sath bara-chhota hona chahiye (state LISTENING). Dobara dabayein — mic band, state IDLE. *(Abhi sirf mic test hai; awaaz se command Phase 5 mein.)*
3. Mic on rakh kar koi text command bhejein — jawab ke baad avatar wapas LISTENING par aana chahiye.
4. **⚙ Settings** kholein:
   - Naam "Zara" aur wake word "Suno Zara" karke save karein — header aur avatar mein naam badalna chahiye. Phir `Suno Zara, Chrome open karo` bhejein — Chrome pehchana jana chahiye.
   - Naam mein `<b>` likh kar save karein — Roman Urdu error aana chahiye.
   - "Avatar states" mein har button daba kar 9 states dekhein (har ek 4 second).
   - Aakhir mein naam wapas **NOVA** aur wake word **Hey NOVA** kar dein.
5. Right panel mein filter (Sab / Tasks / Agents / System / Errors) aur left panel mein kisi agent par click karke uski activity dekhein. "Saaf karein" se list saaf honi chahiye.
6. **Activity Log** tab mein records (waqt, task, agent, permission, execution, verification, admin status) nazar aane chahiye.
7. Command box: `↑` se pichli command wapas aaye, `Esc` se saaf ho, `Ctrl+K` se focus ho.
8. Window chhoti karke dekhein — tabs hamesha nazar aane chahiye.
9. Sab theek ho to approve karein, warna problem batayein.

## Admin manual test (Phase 2, approved)

1. `desktop/` mein `npm start` chalayein. Right panel mein "System scan shuru" aur kuch second baad "System scan mukammal — N applications mili" aana chahiye.
2. Center mein **System Profile** tab kholein. Check karein ke CPU, RAM, GPU, storage, Windows version, mic/speaker/camera, browsers aur default browser aapke PC ke mutabiq sahi hain. Installed applications mein kisi app ko search karein.
3. "Dobara scan karo" button dabayein — scan dobara hona chahiye.
4. **Conversation** tab mein ye commands bhejein:
   - `mera system check karo` → puri system report
   - `RAM check karo`, `Windows ka version batao`, `storage check karo`
   - `kya photoshop installed hai` aur `kya telegram installed hai` (jo installed nahi)
   - `WhatsApp kholo` → "installed hai", lekin open **nahi** hona chahiye
   - `Chrome ko default browser bana do` → koi setting change **nahi** honi chahiye
5. Sab theek ho to approve karein, warna problem batayein.

## Admin manual test (Phase 1, approved)

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
