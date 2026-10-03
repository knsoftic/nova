# NOVA Development Logs

## 2026-10-02

### Task: Phase 1 — Foundation

Status: Complete

Kaam:
- Electron + React + TypeScript + Tailwind desktop app banayi gayi (`desktop/`).
- Python FastAPI backend banaya gaya (`backend/`), sirf `127.0.0.1:8765` par chalta hai (network par expose nahi hota).
- UI aur backend ke darmiyan WebSocket (`/ws`) event system banaya gaya. Events: `TASK_STARTED`, `NOVA_THINKING`, `INTENT_DETECTED`, `NOVA_RESPONSE`, `TASK_COMPLETED`, `TASK_FAILED`, `STATE_CHANGED` waghera.
- NOVA Command Center UI: darmiyan mein NOVA avatar aur state (IDLE, THINKING, COMPLETED, ERROR...), left mein Agents panel, right mein Live Activity, neeche command bar aur "Mic: Off" status.
- AI Provider Manager banaya gaya taa ke provider baad mein badla ja sake. Abhi sirf local rule-based provider hai (Ollama Phase 4 mein).
- Rule-based intent parser: Urdu, Roman Urdu, Hindi, English aur mixed zaban samajhta hai. Intents: greeting, help, open_app, web_search, create_folder, system_info, run_workflow.
- Har jawab Roman Urdu mein hota hai.
- SQLite database (`data/nova.db`): settings, conversations, aur structured activity log (Date, Time, Task ID, Agent, Action, Permission/Execution/Test/Verification/Admin Status, Error, Final Result).
- Password, API key, token waghera log/database mein likhne se pehle `[REDACTED]` kar diye jate hain.
- Electron khud backend start karta hai (agar pehle se na chal raha ho) aur band hone par usay bhi band karta hai.
- Security: Electron mein contextIsolation, sandbox, navigation block; production build mein strict CSP; WebSocket sirf NOVA UI ke origins se accept hota hai.

Imandari se note:
- Phase 1 mein NOVA koi computer action **nahi** karta. Woh command samajh kar sirf batata hai ke ye capability kis phase mein aayegi ("abhi koi action nahi kiya gaya"). Activity log mein `execution_status = intent_only` likha jata hai.

Test:
- Backend automated tests: 36/36 pass (`pytest`) — intent detection, language detection, API, WebSocket event flow, origin rejection, redaction.
- Frontend: TypeScript typecheck aur production build successful.
- Browser mein UI test: "Hey NOVA, Chrome open karo", "کروم کھولو", "mera system profile batao" bheje gaye — sab ka sahi intent aur Roman Urdu jawab aaya, Live Activity mein events nazar aaye.
- Electron app launch ki gayi: production build load hui, backend khud start hua, WebSocket connect hua, app band karne par backend bhi band hua.

Bugs jo test ke dauran mile aur fix kiye gaye:
- React StrictMode mein purana WebSocket naye WebSocket ka reference khatam kar deta tha, is wajah se command send nahi hoti thi. Fix: sirf apna hi reference clear kare.
- Conversation component ka `useEffect` `scrollIntoView` ka Promise return kar raha tha jis se UI crash hoti thi. Fix kar diya.
- `npm install` ke dauran Electron binary download nahi hui thi; `node node_modules/electron/install.js` se download ki gayi.

Verification:
- Backend `/api/status` aur `/api/health` check kiye gaye; UI mein "Backend connected" aur events verify kiye gaye.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Re-test (approval ke baad, Phase 2 se pehle):
- Backend tests 36/36 pass, desktop build successful.
- Electron app launch ki gayi, "VS Code open karo" command bheji gayi — intent `open_app`, Roman Urdu jawab, activity log entry bani. App band karne par backend bhi band hua.

Git:
- Repository initialize ki gayi, Phase 1 commit `a007f3a` (branch `main`).

---

### Task: Phase 2 — System Discovery

Status: Complete (branch `phase-2-system-discovery`, approval ke baad `main` mein merge)

Kaam:
- `backend/nova/discovery/` banaya gaya. NOVA har startup par background mein system scan karta hai (~4 second). Pichla profile scan ke dauran bhi available rehta hai.
- Detect hota hai: CPU (naam, cores, threads), RAM, GPU (naam, memory, dedicated/integrated), drives aur free storage, physical disks, Windows edition/version/build, PC model, microphone, speaker, camera, displays, network, installed applications, browsers aur default browser, khuli applications, startup items, aham Windows services, administrator status.
- Installed apps teen jagah se jama hoti hain: Start menu (Store apps jaise WhatsApp bhi), registry Uninstall keys, App Paths. Koi path hard-code nahi.
- App naam pehchanna: "chrome", "کروم", "क्रोम", "vs code", "واٹس ایپ", "photoshop" waghera sahi app se match hote hain; ghalat spelling ("whatsap") bhi.
- Self-configuration: hardware dekh kar `compute_device`, `multi_monitor_awareness`, `voice_input`, `voice_output` khud settings mein save hote hain. AI model size aur Whisper model sirf **suggestion** hain — kuch bhi install nahi kiya jata.
- System Agent (read-only) ab active hai. Naye commands: "mera system check karo", "RAM check karo", "Windows ka version batao", "storage check karo", "kaun se browsers hain", "kaun si apps chal rahi hain", "mic aur camera check karo", "kya photoshop installed hai", "system dobara scan karo".
- "X open karo" ab batata hai ke X is PC par installed hai ya nahi — lekin launch abhi bhi nahi karta (Phase 6).
- "Chrome ko default browser bana do" jaisi setting change requests pehchani jati hain lekin execute nahi hoti (Permission Engine Phase 7 mein).
- UI: center panel mein "System Profile" tab — live CPU/RAM/uptime, hardware, Windows, storage, devices, self-configuration, browsers, khuli apps, searchable installed apps list, startup items, services, aur jo cheez detect na ho saki uski list.
- API: `GET /api/system/profile`, `POST /api/system/scan`, `GET /api/system/live`, `GET /api/system/apps/find?q=`.
- Scan ke baad profile database mein save hota hai aur dobara parh kar verify kiya jata hai (activity log: `verification_status = passed`).

Is PC ka result (HP EliteBook 845 G8):
- AMD Ryzen 5 PRO 5650U (6 cores / 12 threads), 31 GB RAM, AMD Radeon integrated GPU, C: 21 GB free / 237 GB.
- Windows 11 Pro 25H2 (build 26200). Microphone, speaker, HP HD Camera, 1 display.
- 171 applications (Chrome, VS Code, WhatsApp, Photoshop CC 2019, Edge, Firefox, Brave...). Default browser: Chrome.
- User administrator hai, NOVA non-elevated chalta hai. Collector errors: 0.
- Recommendation: compute = CPU, AI model = small (~3-4B), STT = faster-whisper small (CPU, int8).
- Note: Ollama is PC par pehle se installed hai (startup items mein mila) — Phase 4 mein kaam aayega.

Test:
- Backend automated tests: 82/82 pass — app matching (Urdu/Hindi/English/fuzzy), app merging, recommendations, 16 naye system intents, API, System Agent jawab, aur is PC par **asli Windows scan** ka integration test.
- Frontend: typecheck aur production build successful.
- Browser UI test: System Profile tab mein asli data dikha; commands "mera system profile batao", "kya photoshop installed hai", "واٹس ایپ کھولو", "Chrome ko default browser bana do" ke sahi jawab aaye.
- Electron app: startup par khud scan hua (171 apps, 0 errors), "kaun se browsers hain" ka sahi jawab aaya, band karne par backend bhi band hua.

Bugs jo test ke dauran mile aur fix kiye gaye:
- PC naam do dafa aa raha tha ("HP HP EliteBook") — fix kiya.
- Backend connect hone se pehle command box disabled hota tha aur connect hone ke baad focus nahi hota tha — ab khud focus hota hai.
- Agar UI ka koi hissa crash ho to puri screen blank ho jati thi — ab ErrorBoundary sirf us panel mein error dikhata hai.

Verification:
- Discovery ke baad profile database se dobara parh kar verify hota hai. Read-only commands kuch change nahi karte, is liye un par `verification_status = not_applicable`.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 2 commit `62ad8c4`, `main` mein merge `7a62d98`.

---

### Task: Phase 3 — NOVA UI (Command Center)

Status: Complete (branch `phase-3-nova-ui`, approval ke baad `main` mein merge)

Kaam:
- **Avatar:** 9 states ka alag alag andaaz — IDLE (aahista saans), LISTENING (gola mic ki awaaz ke sath bara-chhota, lehrein), THINKING (ghoomte nuqte), PLANNING (aahista nuqte), WORKING (tez rings), WAITING FOR PERMISSION (amber chamak + "?"), VERIFYING (radar sweep), COMPLETED (✓), ERROR (jhatka + "!"). Settings mein admin ke liye har state ka preview.
- **Voice interface (UI):** asli microphone on/off button, live waveform aur level meter. Mic status hamesha nazar aata hai (Off / On / Blocked / Nahi mila / Error) — status bar aur command bar dono mein. Mic on hone par backend state LISTENING hoti hai; command ke baad wapas LISTENING. UI band ho jaye to mic state khud band hoti hai. Audio na save hota hai na kahin bheja jata hai. Awaaz pehchanna (speech-to-text) Phase 5 mein.
- **Electron permissions:** sirf microphone (audio) ki ijazat, aur sirf NOVA ke apne page ko. Camera aur baqi permissions band.
- **Settings:** assistant ka naam (configurable, Urdu naam bhi), wake word, continuous listening, Windows startup mode (silent/active). `GET/PUT /api/settings`, validation (Roman Urdu errors), SQLite mein save, restart ke baad bhi qaim. Naam/wake word fauran lagu — "Suno Zara, ..." jaisi command pehchani jati hai. Har change activity log mein (sirf badli hui fields).
- **Activity:** right panel mein filters (Sab / Tasks / Agents / System / Errors), agent par click se us agent ki activity, "Saaf karein". Naya **Activity Log** tab — database ka structured log (Date, Time, Task, Agent, Action, Permission, Execution, Verification, Admin status, Result).
- **Status bar:** live CPU/RAM, mic status, connection, Settings button.
- **Command bar:** ↑/↓ pichli commands, Esc se saaf, Ctrl+K ya / se focus.
- Chhoti window mein avatar khud chhota hota hai.

Test:
- Backend automated tests: 96/96 pass (14 naye: settings, validation, restart ke baad settings, Urdu naam, custom wake word, LISTENING state flow, disconnect par mic band).
- Frontend unit tests (naya Vitest setup): 8/8 pass — command history, activity filter, audio level, formatting.
- Typecheck aur production build successful.
- Browser UI test: commands, ↑ history, Esc, settings rename (Zara) + wake word, ghalat naam par error, avatar previews (THINKING, WAITING FOR PERMISSION, COMPLETED), activity filter, Activity Log tab — sab sahi. Settings wapas NOVA kar di gayin.
- Browser pane mein mic block hai, is liye wahan "Mic: Blocked" state test hui. **Asli mic (On + waveform) sirf Electron app mein test ho sakta hai — ye admin manual test mein hai.**
- Electron app launch: backend start, settings sahi, band karne par backend band.

Bugs jo test ke dauran mile aur fix kiye gaye:
- Branch badalne par git ne files CRLF kar di thin, jis se kuch edits chupke se apply nahi huay (settings drawer "load ho rahi hain" par atka) — edits dobara kiye gaye aur `.gitattributes` (LF) add ki gayi.
- Chhoti window mein conversation scroll hone par tabs nazron se ghayab ho jate thay — fix kiya.
- Settings save karne par saari fields "changed" log hoti thin — ab sirf badli hui.

Verification:
- Settings save hone ke baad backend se dobara parh kar check ki gayin; activity log mein entry bani.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 3 commit `80d8c12`, `main` mein merge `27f25b7`.

---

### Task: Phase 4 — AI Brain

Status: Complete (branch `phase-4-ai-brain`, approval ke baad `main` mein merge)

Kaam:
- **Local AI model:** admin ki ijazat se `qwen3:4b` (2.3 GB, Apache 2.0 license) Ollama se download kiya gaya. Sab kuch isi PC par chalta hai, internet par kuch nahi jata.
- **Ollama provider:** model sirf ek fixed JSON schema mein jawab deta hai (intent ka naam aur fields). Model ka jawab sakhti se check hota hai — jo intent list mein nahi (maslan "delete_all_files") woh rad kar diya jata hai. Model khud koi action nahi chala sakta, aur risk level model se nahi, planner ki table se aata hai.
- **AI Provider Manager — 3 modes:** Hybrid (default: seedhi commands rules se fauran, sawal/mushkil jumle model se), Sirf local AI, Sirf rules. Model na ho, slow ho, ya ghalat jawab de to khud rules par fallback, aur wajah batai jati hai.
- **Task Planner:** ek jumle mein kai kaam ("VS Code open karo aur RAM batao") alag steps mein, har step ka agent, risk (low/medium/high) aur status (ready / Phase N mein / permission chahiye). Medium/high risk ka koi kaam Permission Engine (Phase 7) se pehle nahi chalega.
- **Orchestrator:** THINKING → PLANNING → WORKING → COMPLETED. Har step alag activity log mein. Naye events: PLAN_CREATED, STEP_COMPLETED, AI_STATUS, AI_FALLBACK.
- **Sawalon ke jawab:** general sawal ("Pakistan ka capital kya hai") ka chhota jawab Roman Urdu mein. UI mein "AI ka jawab — ghalti ho sakti hai" likha aata hai.
- **Short-term context:** pichli 4 baatein model ko di jati hain, is liye "isko kholo" jaisi baat samajh aati hai (lambi memory Phase 9 mein).
- **Rules behtar:** "zara", "please", "for me", "pehle", "desktop par" jaise fazool alfaaz naam se hatate hain; "zindagi kaisi chal rahi hai" ab system command nahi samjha jata; "isko/usko" model ko bheja jata hai.
- **Warm-up:** startup par model load hota hai aur system prompt pehle se process hota hai taa ke pehli command tez ho.
- **UI:** status bar mein AI status (maslan "AI: qwen3:4b (hybrid)"), Settings mein AI brain section (mode, model, Ollama status, Refresh), har jawab ke sath kis ne samjha (rules / qwen3:4b), aur kai steps wale jawab ke neeche steps ki list.
- **Evaluation script:** `backend/scripts/eval_brain.py` — 26 asli commands (Urdu, Roman Urdu, Hindi, English, mix, compound, sawal, prompt-injection) par brain ko check karta hai.

Test:
- Backend automated tests: 135/135 pass (39 naye): modes, har qisam ka fallback (model nahi / Ollama band / ghalat JSON / na-maloom action / timeout), model output validation, context, planner risk/status, compound commands, API end-to-end. Tests asli model ki jagah fake Ollama use karte hain taa ke har dafa ek jaisa nateeja ho.
- Frontend unit tests: 10/10 pass. Typecheck aur production build successful.
- **Asli model evaluation (is PC par, CPU):**
  - Sirf rules: 18/26 (69%) — sawal aur mushkil jumle nahi samajhta.
  - Sirf local AI: 26/26 (100%), median 5.5s, CPU par.
  - Hybrid (default): 26/26 (100%) — 19 commands rules se fauran (0 ms), sirf 7 model se (median 6.9s).
- Browser UI test (asli model): sawal ka sahi jawab ~7s mein, compound plan steps ke sath, "isko kholo" se Photoshop samjha gaya.
- Electron app: backend start, AI status ready, model se sawal ka jawab, band karne par backend band.

Bugs / masail jo test ke dauran mile aur fix kiye gaye:
- Model ne prompt ki misaal wala jawab hoobahoo copy kiya — misaal badli gayi.
- Ek jawab bohat lamba ho kar 42s laga aur adhoora JSON fallback par gaya — jawab 2 jumlon tak mehdood aur `num_predict` cap.
- Ek dafa model ne Urdu script mein ghalat jawab diya ("Karachi") — prompt mazboot kiya; ab sahi "Islamabad", Roman Urdu mein. Chhota model phir bhi ghalti kar sakta hai, is liye UI mein note.
- Pehli command bohat slow (system prompt process) — warm-up mein ek asli request.
- Rules ki ghaltiyan: "whatsapp for me", "desktop par Projects", "zara VS Code", "pehle chrome", "zindagi kaisi chal rahi hai" — sab fix aur tests add.

Maloom hadood (limitations):
- CPU par model ka jawab 5-15 second leta hai. Hybrid mode isi liye default hai.
- 4B model chhota hai; facts mein ghalti ho sakti hai. Taza maloomat (mausam, khabrein) ke liye Research/Browser Agent Phase 8 mein.

Verification:
- Har command ka plan aur har step activity log mein; read-only steps par `verification_status = not_applicable`.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 4 commit `2fb5eb3`, `main` mein merge `cb88629`.

---

### Task: Phase 5 — Voice

Status: Complete (branch `phase-5-voice`, approval ke baad `main` mein merge)

Kaam:
- **Downloads (admin ki ijazat se):** Whisper `small` (~480 MB, sun'ne ke liye) aur do offline Urdu (Pakistan) Piper voices — `ur_PK-fasih` (mard) aur `ur_PK-aegis_female` (khatoon), ~61 MB har ek. Sab `data/models/` mein (git se bahar). Doosre PC ke liye `scripts/download_voice_models.py`.
- **Awaaz pehchanna (STT):** faster-whisper, CPU int8, Urdu default (Hindi/English/Auto bhi). App ka mic audio 16 kHz mein backend ko jata hai (sirf isi PC par); backend khud pehchanta hai kab bolna shuru/khatam hua.
- **Wake word:** transcript se pehchana jata hai, is liye Settings wala koi bhi naam/jumla chalta hai ("Hey NOVA", "Suno Zara"). Urdu/Hindi script aur Whisper ki ghalat spellings ("ہی نووا", "کی نووا", "نووت") bhi samajh aati hain. Sirf "Hey NOVA" kehne par NOVA "Ji, farmaiye?" bolta hai aur 8 second tak bina wake word command leta hai.
- **Do tareeqe:** mic button = push-to-talk (ek command, phir mic band). "Continuous listening" on ho to mic khula rehta hai aur sirf wake word ke baad wali baat command banti hai.
- **Privacy:** audio kahin save nahi hota. Continuous mode mein bina wake word wali baatein na dikhai jati hain, na log hoti hain, na save hoti hain (test se verify).
- **Urdu awaaz (TTS):** Piper Urdu voice. Test se pata chala ke yeh voice Roman Urdu ko English ki tarah parhti hai, is liye `translit.py` banaya — NOVA ke Roman Urdu jawab bolne se pehle Urdu script mein badalte hain (English alfaaz jaise Chrome/RAM English hi rehte hain). Test check karta hai ke NOVA ke har jawab ka har Urdu lafz lexicon mein ho.
- Lamba jawab (jaise poori system report) ~18 second tak bola jata hai, phir "baqi tafseel screen par hai".
- NOVA apni awaaz khud nahi sunta: bolte waqt mic ki awaaz ignore hoti hai.
- **UI:** mic button ke modes ("Mic: Bolein" / "Mic: On · Hey NOVA"), bolte waqt avatar "SPEAKING", awaaz se di gayi command chat mein, Settings mein Awaaz section (zaban, awaaz, kab bolna hai, "🔊 Awaaz test karein").
- Rules ab Whisper ki Urdu spellings bhi samajhte hain ("آر ایم" = RAM, "وندوز" = Windows) — is se voice command 16s se ~3s ho gayi.
- Electron: sirf audio permission, autoplay jawab ke liye, CSP mein sirf NOVA backend se audio.

Test:
- Backend automated tests: 179/179 pass (44 naye): segmenter, wake word (asli Whisper outputs se), Roman Urdu→Urdu, push-to-talk, continuous (wake ke sath/baghair), follow-up, mute while speaking, model missing, speak modes, validation.
- Frontend: 10/10 tests, typecheck aur build successful.
- **Asli models ke sath end-to-end (`scripts/voice_loopback.py`):** NOVA ki khatoon awaaz ne "user" bankar commands boli, mic jaisa stream kiya gaya:
  - "Hey NOVA, mera system check karo" → suna "میرا سسٹم چیک کرو" → report + Urdu awaaz, ~4.3s mein jawab tayyar.
  - "RAM kitni free hai" → suna "آر ایم کتنی فیح ہے؟" → sahi jawab, ~2.8s.
  - "aaj mausam bohat achha hai" (continuous, bina wake word) → kuch nahi kiya (sahi).
- Browser: Awaaz test — Urdu awaaz chali (4.9s), avatar SPEAKING, phir wapas normal.
- Electron (asli app ke andar check): audio worklet `file://` se load, CSP NOVA ki awaaz allow karti hai, mic permission granted, band karne par backend band.

Bugs / masail jo test ke dauran mile aur fix kiye gaye:
- Whisper "Hey" ko "ہی"/"کی" likhta hai aur "NOVA" ko kabhi "نووت" — wake word nahi pakra jata tha. Fix + tests.
- Hindi "नोवा" Python ke `\w` se toot jata tha — tokenizer badla.
- Custom wake word "Suno Zara" mein "Suno" ko naam samjha ja raha tha — fix.
- Poori system report 45 second boli ja rahi thi — ab ~18 second + "baqi screen par".
- Voice commands LLM par ja kar 10-16s le rahi thin — Urdu-script spellings rules mein add, ab ~3s.
- Phase 4 mein App.tsx ki ek line kharab encoding ke sath commit hui thi ("●" ki jagah "â—") — theek ki.

Maloom hadood (limitations):
- Asli insani awaaz se test sirf admin kar sakta hai (browser pane mein mic block hai). Synthetic awaaz se ~80% wake word pakra gaya; asli awaaz behtar honi chahiye — admin feedback zaroori.
- Whisper small CPU par ~2.7s leta hai; Urdu ki kuch alfaaz ghalat sun sakta hai.
- Urdu awaaz Roman Urdu ke naye/anjaan alfaaz ko kabhi English ki tarah bol sakti hai — admin jo alfaaz batayenge woh lexicon mein add honge.

Verification:
- Har awaaz wali command activity log mein `source = voice` ke sath; read-only kaam par `verification_status = not_applicable`.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 5 commit `7cd6878`, `main` mein merge `419ba78`.

---

### Task: Phase 6 — Computer Control

Status: Complete (branch `phase-6-computer-control`, approval ke baad `main` mein merge)

Kaam:
- **Application kholna (asli):** sirf System Discovery wali apps khul sakti hain (Start menu AppID ya discovered exe se) — user ya AI model se aaya koi path/command kabhi nahi chalta. Kholne ke baad **verification**: nayi window nazar aaye to "khul gaya", pehle se khuli ho to "saamne la diya", 15 second mein window na aaye to imandari se batata hai.
- **Windows:** kisi app par jana (focus), minimize, maximize, restore, desktop dikhana — har ek ke baad state check hoti hai. "Ye window" ka matlab: aap ki pichli window (NOVA ki apni nahi).
- **Screen samajhna:** Windows UI Automation (buttons/fields ke asli naam) + Windows ka built-in OCR (likha hua text). Window doosri windows ke peeche bhi ho to parh leta hai. Sab local.
- **Screenshot:** `data/screenshots/` mein, file ban'ne ki verification.
- **Keyboard/mouse (SendInput):** copy (clipboard badla ya nahi — verify), aur paste, type, click, close, save waghera. Copy/select-all low risk — chalte hain. **Paste, type, click, app band karna, save: medium risk — banaye aur test kiye gaye, lekin Permission Engine (Phase 7) tak locked.** Test se verify ke locked commands par desktop ko haath bhi nahi lagaya jata, aur AI model ko dhoka de kar bhi lock nahi tootta.
- Naye commands (Roman Urdu/English/Urdu/Hindi): "Chrome pe jao", "Chrome minimize karo", "desktop dikhao", "screen par kya hai", "screenshot lo", "copy karo", "likho: ...", "OK par click karo", "Chrome band karo". "likho: ..." ka text kabhi commands mein nahi toot'ta (maslan "likho: Chrome kholo aur RAM batao" sirf likhega).
- Naye events: VERIFICATION_STARTED / PASSED / FAILED; avatar VERIFYING state; activity log mein asli verification status.

Test:
- Backend automated tests: 234/234 pass (55 naye) — fake desktop par: launch + verify, unverified ka imandar jawab, na-installed app, focus fail, window control, screen read, screenshot, copy + clipboard check, locked actions (desktop untouched), AI model se lock bypass ki koshish, input events (Urdu Unicode typing), window matching, launcher logic.
- Frontend: 10/10 tests, build successful.
- **Is PC par asli test (Calculator — bezarar):** kholna 0.8s mein verify, minimize/focus/maximize/restore sab verify, screen read 0.7s, screenshot, "band karo"/"type karo" locked, Telegram "nahi mila". Test ke baad Calculator band aur screenshot delete kiya.
- AI brain eval (36 commands, 10 naye computer-control): hybrid 36/36 (ek ghalti fix ke baad), LLM-only 35/36 → prompt fix ke baad wo case bhi sahi.
- Browser UI: compound "Calculator kholo aur RAM batao" ✓✓, "Calculator band karo" 🔒.
- Electron app: asli backend se Calculator khula aur verify hua.

Bugs jo test ke dauran mile aur fix kiye gaye:
- 64-bit Windows handles ctypes mein overflow ho rahe thay (window capture) — sahi types diye.
- "WhatsApp wali window" mein "wali window" app ke naam mein shamil ho raha tha — fix.
- AI model "likho: ..." ko sawal samajh raha tha — prompt mein misaal.
- Naye Urdu alfaaz ka awaaz test (lexicon coverage) ne computer agent ke jawabon ke anjaan alfaaz pakray — add kiye.

Maloom hadood (limitations):
- Windows administrator (elevated) apps mein NOVA type/click nahi kar sakta (Windows ki hifazat).
- Windows OCR sirf English text parhta hai (is PC par sirf English OCR language hai); Urdu text screen se nahi parha jata.
- Kuch apps (jaise Claude/Electron apps) apne buttons accessibility mein kam dikhati hain — un par OCR kaam aata hai.

Verification:
- Har action ka verification status activity log mein (passed / failed / unverified / not_applicable).

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 6 commit `a8543f4`, `main` mein merge `7fb4721`. (Pehli commit koshish message ke quotes ki wajah se fail hui thi — kuch commit nahi hua tha; dobara sahi tareeqe se ki gayi.)

---

### Task: Phase 7 — Permission Engine

Status: Complete (branch `phase-7-permission-engine`, approval ke baad `main` mein merge)

Kaam:
- **Risk classification (context ke sath):** planner ka risk + jagah aur kaam dekh kar: Terminal/PowerShell mein type ya Enter → high; password/card jaisa text → high; "Delete/Send/Pay/Buy/Confirm" jaise button par click → high; app band karna → medium (unsaved window ho to bataya jata hai).
- **Ijazat maangna:** risky step se pehle NOVA ruk jata hai (avatar "?" WAITING FOR PERMISSION), dialog dikhata hai — kaam, kis window mein, khatra aur wajah, countdown. Default focus **Nahi** par, Esc = Nahi. 60 second mein jawab na aaye to **Nahi**. NOVA window khud saamne aa jati hai (Electron).
- **Jawab ke tareeqe:** dialog button, command box mein "haan"/"nahi" (Urdu/Hindi bhi), ya awaaz se — awaaz wali command ka sawal NOVA bolta hai aur phir mic khud kholta hai; continuous mode mein jawab ke liye wake word zaroori nahi.
- **Yaad rakhna:** sirf medium risk, aur sirf usi app mein usi kaam ke liye (maslan "Notepad mein paste"). High risk kabhi yaad nahi rakha jata. Settings mein list aur "Hatao".
- **Audit:** har sawal `permission_requests` table mein (kya, risk, faisla, kis ne — UI/text/voice/rule/timeout, kab); activity log mein bhi.
- **Ab chalne lage (ijazat ke baad):** type karna (verify: field mein text nazar aaye), click (pehle accessibility "Invoke", warna mouse; button na mile to imandari se batata hai), app band karna (verify: window band hui ya save ka pooch rahi hai), paste/save/undo waghera.
- **Hifazat ki doosri teh:** ComputerAgent bina orchestrator ki di hui ijazat ke risky kaam karne se khud inkaar karta hai.

Test:
- Backend automated tests: 279/279 pass (45 naye): classification, scope, haan/nahi parsing, approve/deny/timeout, text "haan", yaad rakhna + hatana, high risk kabhi yaad nahi, compound mein sirf risky step ka sawal, click fallback, band na hone wali window, agent ka inkaar, sawal bolna.
- Frontend: 10/10 tests, build successful.
- Browser UI (asli backend): dialog sahi dikha; Esc → denied; Calculator kholna + "band karo" → Haan → "band ho gaya (Verify)".
- Electron app ke andar: dialog aaya, focus "Nahi" par, attention function mojood, deny ka jawab sahi.

**Test ke dauran ek waqia (incident) — imandari se:**
- Browser pane mein "hello world type karo" test karte waqt dialog **"Haan" + "yaad rakhna" ke sath approve** hua (audit: `user_ui`, remembered=1) aur NOVA ne "hello world" **Claude app ki window** mein type kar diya (development mein NOVA ka UI usi window ke andar chal raha tha). Mera Esc sirf "Nahi" bhejta hai — dobara test mein Esc ne sahi "Nahi" bheja. Approve shayad shared browser pane mein kisi click se hua.
- Fauran: ghalti se bana rule (`type@claude.exe`) hata diya gaya.
- **Asal masla fix kiya:** jis window mein NOVA ka apna UI chal raha ho (typed command ke waqt jo window saamne ho), wo ab kabhi type/click/"ye window" ka target nahi banti — chahe NOVA Electron mein ho ya kisi browser mein. Regression test add kiya. Live dobara check: target ab Claude window nahi.

Maloom hadood (limitations):
- Admin (elevated) apps mein type/click Windows ki taraf se band hai.
- Kuch apps typed text wapas parhne nahi deti — tab NOVA "unverified" batata hai.

Verification:
- Activity log mein permission_status: approved_by_user / approved_by_saved_rule / denied / timeout, aur action ka verification.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 7 commit `274da28`, `main` mein merge `fae39a2`.

---

### Task: Phase 8A — Browser Agent + Research Agent

Status: Complete (branch `phase-8a-browser-research`, approval ke baad `main` mein merge)

Phase 8 teen hisson mein (admin ka faisla): **8A** Browser + Research, **8B** File + Coding, **8C** System settings + Communication + Design. Har hissa alag test aur approval ke sath.

Kaam:
- **Browser Agent:** NOVA ab apna browser chalata hai — installed Google Chrome (ya Edge, Settings se), Playwright ke zariye, NOVA ki **alag profile** (`data/browser-profile`) ke sath: aap ke passwords, cookies aur logins istemal nahi hote. Koi naya browser download nahi hua.
  - Website kholna ("example.com kholo", "youtube kholo" — jo site app ki tarah installed na ho wo browser mein khulti hai). Verify: page load hua aur address sahi hai.
  - Anjaan naam (bina dot ke) → search engine par search (Settings: Google / Bing / DuckDuckGo).
  - Page parhna aur khulasa ("is page ko summarize karo") — local AI 3-5 points deta hai.
  - Scroll, peeche, aage, reload — verify ke page badla ya nahi (chhote page par imandari se "page wahi raha").
  - Click, type, download — **hamesha ijazat se**. Ijazat se pehle NOVA page par asli element dhoondta hai aur dialog mein uska asli naam dikhata hai (maslan "Learn more", ya "Search Wikipedia" khane mein). Element na mile to bina pooche "nahi mila". Ijazat ke baad page badal gaya ho (element ka text alag ho) to click nahi karta.
  - "Delete / Buy / Pay / Send..." jaise buttons aur `.exe/.msi` jaise downloads **high risk** (laal dialog, yaad nahi rakhe jate).
  - Password, card number, CVV, OTP wale khane: NOVA **bina pooche inkaar** karta hai ("NOVA password kabhi nahi likhta").
  - Downloads `Downloads\NOVA` mein, file ka naam saaf karke. Verify: file bani.
  - User NOVA ke browser window mein ho aur "X par click karo" kahe, to ye kaam Browser Agent karta hai (desktop click nahi).
- **Research Agent:**
  - Web search sirf official API se: **Brave Search API** (admin ki apni key) — Google/Bing ke pages scrape nahi kiye jate. Key na ho to Wikipedia API.
  - Taza sawal ("Lahore ka mausam", "dollar ka rate", "latest news"): Brave se 5 results + local AI ka 1-4 jumlon ka jawab + Sources (links). Key na ho to NOVA imandari se batata hai ke Wikipedia par live maloomat nahi hoti, aur Brave key ya browser search ka tareeqa batata hai — ghalat articles nahi dikhata.
  - Research report ("X ke baare mein research karo"): mukhtalif websites ke 3 sources parhta hai, local AI report likhta hai (khulasa, 4-6 aham baatein, kami/ikhtilaf) — `Documents\NOVA\Research\<tareekh>_<topic>.md` mein Sources aur disclaimer ke sath. Verify: file bani.
- **Hifazat:**
  - Safe fetch: sirf public internet. localhost, 127.x, 10.x, 192.168.x, 169.254 (cloud metadata), IPv6 local waghera block. Har redirect dobara check hota hai, aur connection usi IP se hota hai jo check hui (DNS rebinding se bachao). Sirf HTML/text, 2 MB tak.
  - Web ka text "untrusted" hai: local AI ko sakht hidayat hai ke us mein likhi hidayaat par amal na kare. AI ka jawab sirf dikhaya/bola jata hai, kabhi execute nahi hota.
  - Brave key Windows DPAPI se encrypted (sirf isi user/PC par khul sakti hai). API key kabhi wapas nahi deti — sirf "••••1234". Activity log aur server logs mein key nahi jati (test se verify).
- **Local AI behtar:** chhota model khulase mein apni "soch" English mein likh deta tha ("Okay, the user wants...") aur bohat slow tha. Ab jawab JSON schema mein majboor hai (points / jumle), prompt mein Roman Urdu misaal, chhota input, aur har call ka ek hi context size (model dobara load nahi hota). Nateeja: page khulasa 52s → ~30s, report 204s → ~110s, "soch" wala text khatam.
- **UI:** Settings mein "Web aur browser" section — Brave key (likh kar save, dobara nazar nahi aati, Hatao), search engine, Chrome/Edge. Agents panel mein Browser aur Research Agent active; File/Coding "Phase 8B", Design/Communication "Phase 8C". Jawab mein https links clickable hain (default browser mein khulte hain).
- AI brain: 8 naye intents (open_website, read_page, browser_nav, browser_click, browser_type, download, research, web_answer) — rules aur LLM prompt dono mein.

Test:
- Backend automated tests: 337/337 pass (58 naye) — SSRF block list, IP pinning, redirects, size/type, text extraction, Brave/Wikipedia (disambiguation pages skip), encrypted secret (kabhi wapas nahi, ghalat key echo nahi), browser flows (fake browser par), click/type/download ijazat, password/card par inkaar, page badalne par click na karna, research report sirf public sources se, AI "soch" filter, ghalat JSON par fallback, search phrasing. Tests asli browser ya internet ko haath nahi lagate.
- Frontend: 12/12 tests (link parsing naya), typecheck aur production build successful.
- AI brain eval (47 commands, 11 naye browser/research): sirf rules 42/47 (baqi 5 aam sawal hain jo model ke liye hain), **hybrid 47/47** (median 7.9s), sirf LLM 47/47 (median 9.0s).
- **Is PC par asli test:**
  - NOVA ki Chrome window apni profile se ~3s mein khuli; example.com khula + verify (2.7s).
  - Khulasa ~30s, bina "soch" ke.
  - Scroll (chhota page — imandari se "page wahi raha"); "Learn more" click ijazat se → page badla (verify); peeche.
  - "Delete link par click karo" — nahi mila, poocha bhi nahi.
  - wikipedia.org par "search box mein Islamabad likho" → dialog → Haan → likha gaya aur verify (0.5s).
  - "Islamabad ke baare mein research karo" — Wikipedia ke 3 sources, Roman Urdu report, ~110s.
  - SSRF: localhost/private addresses block; Wikipedia ka asli TLS fetch pinned IP ke sath.
- Browser UI: Settings Web section; ek nakli test key save → "••••0000" → Hatao (activity log mein sirf "save hui (encrypted)", key kahin nahi); sources ke links clickable; "dollar ka rate kya hai" (bina key) → imandar jawab fauran.
- Electron app: production build launch hui, "NOVA Command Center" window, backend errors: 0.

Bugs / masail jo test ke dauran mile aur fix kiye gaye:
- Khulase aur report mein AI ki English "soch" — JSON schema se fix.
- Wikipedia se report mein sirf 1 source (har source alag website ka hona zaroori tha) — ab pehle alag websites, phir usi site ke doosre pages; disambiguation pages skip.
- "dollar ka rate kya hai" bina Brave key ke Wikipedia se film/TV articles le aaya aur AI ne sawal hi dohra diya — ab live sawal par Wikipedia istemal nahi hota (imandar jawab), aur sawal dohrane wala jumla filter hota hai.
- Wikipedia search Roman Urdu alfaaz ("ka", "kya", "hai") ki wajah se ghalat articles laata tha — ab sirf asal alfaaz search hote hain.
- "google par ... search karo" / "google pe dekho ..." ko live sawal samjha ja raha tha — ab browser search; "dollar rate google par search karo" mein "google par" query se hataya.
- "search box mein ... likho" Wikipedia par khana nahi dhoond pata tha ("search box" vs "Search Wikipedia") — ab "box/field/khana" hata kar aur search fields bhi dhoondta hai; dialog mein khane ka naam bhi aata hai.
- AI model "Pakistan ka capital kya hai" ko live sawal samajhne laga — prompt mein misaalen di gayin, hybrid wapas 47/47.
- "aage jao" pehchana nahi jata tha — add kiya.
- Mere test se bani 2 research reports `Documents\NOVA\Research` se Recycle Bin mein bheji gayin.

Maloom hadood (limitations):
- Brave key ke baghair taza maloomat (mausam, rate, khabrein) nahi milti — sirf browser search. Brave ki free key admin ko khud banani hogi.
- Local AI (CPU) slow hai: khulasa ~30s, report 1-2 minute. Chhota model kabhi khulasa English mein deta hai (khaas kar English page par), aur facts mein ghalti ho sakti hai — report mein disclaimer hai.
- Login wali sites (Gmail waghera) NOVA ki alag profile mein logged out hain. NOVA password nahi likhta, is liye login admin ko khud karna hoga.
- Kuch websites automation ko CAPTCHA dikhati hain — NOVA CAPTCHA hal nahi karta.
- Ek dafa (dobara nahi hua) page khulne ke foran baad khana dhoondne mein 21s lage — nazar rakhi ja rahi hai.

Verification:
- Website: page ka address/title; click: page badla ya nahi; type: khane mein wahi text; download: file bani; report: file bani. Activity log mein verification_status.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 8A commit `d2abafa`, `main` mein merge `9279be9`.

---

### Task: Phase 8B — File Agent + Coding Agent

Status: Complete (branch `phase-8b-file-coding`, approval ke baad `main` mein merge)

Kaam:
- **Kaam ki hadood (admin ka faisla "Common + projects"):** Desktop, Documents, Downloads, Pictures, Music, Videos (registry se asli jagah, OneDrive par bhi) aur Settings ke project folders (default `C:\xampp\htdocs`). Har path pehle poora resolve hota hai, is liye `..` ya shortcut/link se bahar nahi ja sakte. In folders ke andar bhi NOVA:
  - `.env`, private keys, credential files na kholta hai na badalta hai (search mein bhi nahi dikhti);
  - `.git` ke andar kuch nahi badalta; NOVA ka apna program folder sirf parh sakta hai, aur NOVA ka data folder (database, browser profile, models) parhta bhi nahi;
  - bunyadi folders (Desktop, Documents...) ko delete/rename/move nahi karta.
- **File Agent:**
  - Dhoondna (naam ya qism: "pdf files", "tasveerein"), folder ki list, banana (file/folder; "... banao aur us mein ... likho"), kholna (documents apne program mein, text/code VS Code mein; .exe/.bat/.ps1/.js jaise programs **kabhi nahi chalata**), parhna (text/code, Word, PDF, Excel) aur khulasa (local AI), copy (purani file kabhi overwrite nahi — "name - Copy.txt"), folder report (Documents\NOVA\Reports mein).
  - **Ijazat se:** naam badalna, move, edit (aakhir mein likhna / text badalna), organize, undo.
  - **Delete hamesha Recycle Bin mein** (Windows ka SHFileOperation, "permanent delete" se pehle Windows khud warning deta hai) — har dafa poocha jata hai, kabhi "yaad" nahi rakha jata; 100+ files ya 1 GB+ wala delete **high risk**. Jis drive par Recycle Bin nahi wahan NOVA delete nahi karta.
  - Edit se pehle purani file ka **backup**; "pichla file kaam undo karo" aakhri rename/move/organize/edit/naya-banaya wapas karta hai (agar baad mein file badli gayi ho to undo inkaar karta hai taa ke naya kaam na mite).
  - Organize: files qism ke folders mein (Images, Documents, Videos, Archives, Installers, Code...) — shortcuts, adhoori downloads aur abhi badli hui files nahi hilti; project folders kabhi organize nahi hote.
  - Naam se dhoondna: ek se zyada mile to list dikha kar poochta hai ("pehli wali", "2 number wali"); "isko/is file" pichli file ko kehte hain.
- **Coding Agent:**
  - Projects ki list, project ka jaiza (Node/PHP/Python, frameworks, npm scripts, git branch/changes, tests), VS Code mein kholna (verify: VS Code window mein project ka naam).
  - Tests chalana (npm test / pytest project ke .venv se / PHPUnit), errors check (project ke typecheck/lint scripts; built-in python compileall, php -l, node --check), project commands (npm scripts jaise build, dev server alag terminal window mein, install, git status/diff/log).
  - **Sirf tay shuda commands** — project ke apne npm scripts (naam package.json se), tests, install, sirf-parhne-wali git commands aur syntax checks. Koi shell nahi, timeout ke sath; zyada der chale to poora process tree band. System Python mein packages kabhi install nahi (sirf project ka .venv).
  - Project ka apna code chalne wale kaam (tests, npm scripts) ijazat se; sirf syntax check aur git status bina pooche. Install (internet se packages) har dafa poocha jata hai.
  - Error samjhana (local AI, Roman Urdu) aur **error theek karna / code badalna:** local AI chhoti find/replace tabdeeli tajweez karta hai → file se exact match check → syntax check (Python, JSON, PHP, JS) — syntax kharab karne wali tajweez user tak pohnchti hi nahi → **dialog mein diff (laal/hari lines)** → Haan ke baad backup ke sath likhna → wahi check dobara chala kar verify ke error khatam hua. Agar tajweez ke baad file badal gayi ho to purani tajweez apply nahi hoti.
- **Permission Engine:** dialog mein ab "preview" — diff, organize ka plan, ya exact command. File/code kaamon ke liye "yaad rakhna" usi folder/project/command tak mehdood; delete/edit/code ki tabdeeli kabhi yaad nahi rakhi jati. Tests ka nateeja activity log ke `test_status` mein.
- **AI brain:** 20 naye intents (rules + LLM). "nova project kholo" mein "nova" ab wake word samajh kar hataya nahi jata. "notes.txt mein ... likho" jaisa text "aur" par do commands mein nahi toot'ta.
- **UI:** Settings mein "Files aur code projects" (allowed folders, project folders add/hatao); permission dialog mein diff/plan; jawab mein code/output monospace block mein; File/Coding Agent active.

Test:
- Backend automated tests: 419/419 pass (82 naye) — scope (bahar, `..`, secrets, .git, NOVA ki files, bunyadi folders), search, Word/Excel/PDF, CRLF/UTF-8, har file kaam ki verification, Recycle Bin (fake), backup + undo, organize plan + undo, projects ko organize na karna, poore API flows ijazat ke sath, ambiguous naam, context ("isko", "pehli wali"), bara delete high risk, settings validation, projects/tests/commands (fake runner), error fix diff + verify + undo, syntax-kharab tajweez rad, badli hui file par tajweez rad, asli subprocess runner (exit code, timeout par process tree band, per-file check), error parsers, rules/LLM parsing. Tests asli folders, Recycle Bin ya commands ko haath nahi lagate.
- Frontend: 14/14 tests, typecheck aur build successful.
- AI brain eval (60 commands, 13 naye file/coding): sirf rules 55/60 (baqi 5 aam sawal), **hybrid 60/60**, sirf LLM 59/60 (median 14.9s). Note: test ke waqt PC par ek anjaan `cmd.exe` process (subah 08:13 se, 24 threads) CPU ~100% le raha tha, is liye AI ke waqt Phase 8A se zyada aaye (pehle ~8s) aur ek dafa 45s timeout hua.
- Naye intents ki wajah se LLM ne kuch cheezein ghalat samjhi thin ("VS Code chala do" → project command, "notes.txt mein likho" → type_text, mausam → web_search) — prompt mein fark wazeh kiya aur misaalen di, "nova project" ka naam saaf kiya.
- **Is PC par asli test (sirf apne banaye test folder `Documents\NOVA-Test-8B` aur 2 demo projects mein; file names mein "nova8btest" taa ke search aap ki files na dikhaye):**
  - "nova8btest files dhoondo" → 5 files (1.5s); folder ki list; Word (.docx) parhna.
  - "NOVA-Test-8B folder mein ... banao aur us mein doodh aur chai likho" → file + text (fix ke baad rules se, 1.5s).
  - Likhna → dialog mein preview `+ kal meeting 5 baje` → Haan → verify. Naam badalna → dialog mein dono naam → verify. Copy → "- Copy.txt".
  - Organize → dialog mein plan (Archives/, Documents/, Images/) → Haan → 3 files verify → "pichla file kaam undo karo" → sab wapas.
  - Delete → **asli Recycle Bin** → verify (wahan se Restore ho sakti hai). `.env parho` → inkaar. Folder report bani.
  - Python demo project: errors check (compileall) → `app.py:5 SyntaxError: '(' was never closed` → "error theek karo" → **asli local AI ne 18s mein sahi fix diya** (`print(greet("NOVA"))`), dialog mein diff → Haan → dobara compile → "wo error ab nahi hai".
  - Node demo project: `npm test` aur `npm run build` asli npm se (ijazat ke baad), output dikha, `test_status = passed`.
  - "nova project mein git status chalao" → bina pooche, output dikha.
  - "nova-demo-8b project kholo" → VS Code khula aur verify (4.1s); test ke baad sirf wahi window band ki.
  - UI: permission dialog mein laal/hari diff; Esc ("Nahi") par file nahi badli; file ka content monospace block mein; Settings mein Files section.
  - Test ke baad saari test files aur demo projects Recycle Bin mein, test report aur backups hata diye, undo journal saaf.
- Electron app: production build launch hui, "NOVA Command Center" window, backend errors: 0.

Bugs jo test ke dauran mile aur fix kiye gaye:
- **Asli test mein pakra gaya:** "NOVA-Test-8B" mein se "NOVA-" wake word samajh kar hat jata tha ("Test-8B" bach jata). Phir "Test-8B" folder ka naam htdocs ke ek project "test web" se *milta julta* samjha gaya aur test file us project mein ban gayi (bina pooche, kyunke banana low risk hai). Test ki file foran Recycle Bin mein gayi aur us project mein kuch nahi bacha; galat folder ki report bhi hata di. **Fix:** naam se juda "NOVA-" ab wake word nahi; folder ka naam **sirf poora (exact)** match hota hai — milta julta ho to NOVA list dikha kar poochta hai; project sirf "... project" kehne par dhoondha jata hai. Regression tests add.
- Kamyab command (maslan git status) ka output nahi dikhta tha — ab dikhta hai.
- Windows ka Temp folder 8.3 chhote naam (QADRIL~1) se aata hai — project folder validation `realpath` se.
- Code edit mein local AI indentation chhor deta hai — line-wise asli indentation wapas.
- `.env` jaisa naam "nahi mila" ki jagah ab saaf inkaar.
- **Asli test mein:** lamba jumla ("... banao aur us mein doodh aur chai likho") LLM ko ja raha tha aur model ne text chhor diya — text wali commands ab rules hi samajhte hain (lambai text ki wajah se hai, ulajhan ki wajah se nahi).
- **Asli test mein:** error ki wazahat English mein aayi; Roman Urdu misaal di to model ne misaal hi copy kar di — ab copy hui misaal hata di jati hai.

Maloom hadood (limitations):
- Ek hi jumle mein "X banao aur isko move karo" — "isko" abhi pehle hisse ki nayi file ko nahi pehchanta (sab steps pehle tayyar hote hain); alag alag kahein.
- Local AI (CPU) code ki tabdeeli/wazahat mein 20-90 second leta hai aur 160 lines se bari file ek sath nahi badalta (error wali jagah ke aas paas hi). Chhota model ghalat tajweez de sakta hai — is liye diff dikhaya jata hai, syntax check hota hai aur undo maujood hai.
- Error ki wazahat kabhi English mein aati hai (chhota model technical baat English mein karta hai) — maana sahi hota hai.
- Recycle Bin se wapas lana NOVA khud nahi karta (Recycle Bin → Restore).
- Dev server alag terminal window mein chalta hai; NOVA usay band nahi karta (window band kar dein).
- Search ek waqt mein ~4 second / 80,000 cheezon tak; bohat bare folders mein folder ka naam bata kar dhoondein.

Verification:
- Har file kaam ke baad asli halat check (file bani/hili/gayi, text dobara parha, copy ka size/count, organize mein har file). Code fix: wahi check dobara. Tests: `test_status`. Activity log mein permission/verification.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 8B commit `9b478aa`, `main` mein merge `8687054`.

---

### Task: Phase 8C — System settings + Communication Agent + Design Agent

Status: Complete (branch `phase-8c-system-comm-design`, approval ke baad `main` mein merge)

Admin ke faisle (is phase ke shuru mein): messages **WhatsApp + Outlook** (har bhejne se pehle recipient aur poora text dikha kar ijazat), settings **aam settings** (volume, brightness, dark mode, Wi-Fi, Bluetooth; baqi ke liye Settings page; security kabhi nahi), design **image tools**.

Kaam:
- **Windows settings (System Agent):**
  - Volume (number, "thori kam/zyada", "aadhi", "full"), mute/unmute, brightness (laptop ki apni screen) — fauran, aur har badlaav ke baad dobara parh kar verify ("ab 30% hai").
  - Dark/light mode aur Wi-Fi/Bluetooth **off** karna ijazat se (wajah dialog mein: "Internet band ho jayega", "headphones disconnect ho jayenge"); on karna seedha.
  - Default browser jaisi cheezein Windows khud kisi program ko badalne nahi deta — NOVA sahi Settings page (Default apps) khol deta hai aur batata hai. "display/wallpaper/update/... settings kholo" bhi.
  - **Security settings (Defender, firewall, UAC, BitLocker, passwords) NOVA kabhi nahi badalta** — saaf inkaar.
- **Communication Agent:**
  - **Contacts:** NOVA ki apni list (Settings → Contacts, ya "Ali ka number 0300 1234567 save karo"); numbers "+92 300 1234567" format mein. NOVA aap ki WhatsApp chats/contacts mein **khud kabhi nahi dhoondta** — is liye ghalat "Ali" ko message jane ka khatra nahi. Command mein likha number/email bhi chalta hai.
  - **WhatsApp:** official click-to-chat link se bilkul usi number ki chat khulti hai aur text message box mein aata hai. NOVA pehle check karta hai ke box mein yahi text hai (accessibility/OCR); confirm na ho to **kuch nahi bhejta**. Enter sirf tab dabata hai jab WhatsApp hi saamne ho; baad mein check karta hai ke box khaali aur text chat mein hai.
  - **Email:** Outlook account ho to Outlook se (Sent Items mein verify, Outbox mein ho to batata hai), attachment ke sath bhi (file allowed folders se, 20 MB tak). Outlook account na ho (is PC par yahi haal hai) to draft default mail app mein khulta hai — Send aap dabate hain; NOVA "bhej diya" nahi kehta.
  - Har bhejna **har dafa poocha jata hai** (kabhi yaad nahi), dialog mein recipient + poora text; message mein password/OTP/card jaisi cheez ho to **high risk**. "... ke liye message prepare karo ke ..." → local AI draft likhta hai, bhejta nahi.
- **Design Agent:**
  - Tasveer: exact size (1080x1080, Instagram post/story, YouTube thumbnail, DP...) bina khinchay crop, % chhota, format (png/jpg/webp/pdf...), compress (size pehle/baad batata hai), ghumana, flip, black & white, caption (neeche patti), watermark (corner ki roshni dekh kar kala ya safed). **Original kabhi nahi badalta** — hamesha nayi file, aur nayi file khol kar size/format verify.
  - Template designs: post, story, banner, thumbnail, poster, card... — gradient background, rang ("neela", "sunehra"...), text khud fit hota hai; Pictures\NOVA\Designs mein save aur khul jata hai.
  - File ko Photoshop / Paint / Word / Excel / PowerPoint / Notepad / VS Code mein kholna (app ka path Windows registry se; programs nahi kholta), verify: window.
- **Permission Engine:** agent apni resolved halat ke hisaab se kam se kam risk aur wajah de sakta hai (dark mode, Wi-Fi off, message bhejna). Contact ka field model schema mein `contact_name` — `name` rakhne se intent ki list kharab ho jati (test ne pakra).
- **UI:** Settings mein Contacts section (add/hatao, number check); Design aur Communication Agent active; permission dialog mein message ka poora text.
- **AI brain:** 8 naye intents, rules + LLM. "awaaz band karo"/"wifi band karo" ab setting hain (app band karna nahi); "isko band kar do" pehle ki tarah app band karna.

Test:
- Backend automated tests: 474/474 pass (55 naye) — settings (level words, verify, ijazat, security inkaar, default browser page), contacts (numbers, email, API validation), WhatsApp (dialog mein text, har dafa poochna, inkaar par WhatsApp khulta bhi nahi, confirm na ho to na bhejna, Enter sirf WhatsApp mein, anjaan naam), password wala message high risk, local AI draft, email Outlook/bina Outlook/attachment, image edits (nayi file, original same, size verify), designs, Urdu script inkaar, rules/LLM parsing. Tests asli settings, WhatsApp, email ko haath nahi lagate.
- Frontend: 15/15 tests, typecheck aur build successful.
- AI brain eval (70 commands, 10 naye): sirf rules 66/70 (baqi 4 aam sawal), **hybrid 70/70**, sirf LLM 68/70 (median 9.4s; dono ghaltiyan hybrid mein rules sambhal lete hain).
- **Is PC par asli test:**
  - Volume 78% → 30% → "thori zyada" 40% → mute/unmute; brightness 100% → 70%; light → dark → light (ijazat ke sath) — sab verify; test ke baad **sab pehle jaisa** (volume 78%, brightness 100%, light mode, Wi-Fi/Bluetooth on).
  - "firewall band karo" → inkaar. "wifi band karo" → dialog (Internet band ho jayega) → Nahi → Wi-Fi on raha. "Chrome ko default browser bana do" → Default apps page khula (verify).
  - Test contact save/list; usay WhatsApp message → dialog mein number aur text → **Nahi** (koi message nahi bheja gaya); contact hata diya.
  - Sandbox tasveer: 1080x1080, png, compress (432 KB → 203 KB), 90° ghumana, black & white, watermark, caption — sab nayi files, verify; YouTube thumbnail design bana aur khula; "isko Paint mein kholo" → Paint mein khula (verify).
  - UI: Contacts section — ghalat number par error, sahi par "+92 300 0000001", Hatao.
  - Test ke baad: khuli windows (Settings, Photos, Paint) band, sandbox aur design Recycle Bin mein, test contacts hata diye.
- **Jaan bujh kar asli test nahi kiya:** Wi-Fi/Bluetooth off (meri apni internet connection aur aap ke headphones/mouse), aur koi asli WhatsApp message ya email — ye admin test mein aap khud karein.

Bugs / masail jo test ke dauran mile aur fix kiye gaye:
- Model schema mein contact ke liye `name` field ne intent ke naam ki list mita di thi (model koi bhi intent naam likh sakta) — `contact_name` kiya; test ne pakra.
- "awaaz band karo" / "firewall band karo" app band karna samjha jata — ab setting (firewall par inkaar).
- "isko ... kar do" har cheez tasveer edit ban jati — ab tasveer ke kaam ka lafz zaroori.
- "WhatsApp par Sara ko likho" mein naam "WhatsApp par Sara" ban raha tha — fix.
- "90 degree ghumao" mein "ghumao" kat jata tha — fix.
- Asli tasveer dekh kar: caption patti mein text neeche chipka hua tha, safed watermark halki tasveer par nazar nahi aata tha — dono theek (asli glyph height, corner ki roshni).
- Pehle ke phases ki safai: lexicon mein "bare" do dafa (do mukhtalif maane) — ek rakha; ek test file mein bekaar imports.

Maloom hadood (limitations):
- Is PC par Outlook mein email account set nahi — email abhi sirf draft (mail app) ke tor par; account set hone par Outlook se bhejna aur verify chalega.
- WhatsApp verification OCR/accessibility par hai: Urdu script ya sirf emoji wale message ki tasdeeq OCR nahi kar sakta — tab NOVA nahi bhejta aur batata hai (aap khud Enter dabayein).
- Brightness sirf laptop ki apni screen; bahar wale monitor ki nahi.
- Design text sirf Roman Urdu/English (Urdu script ke liye text-shaping library nahi).
- Wi-Fi/Bluetooth Windows ki radio ijazat par chalta hai; kuch PCs par adapter driver ye na de to NOVA batata hai.

Verification:
- Settings: har badlaav ke baad dobara parhna. WhatsApp: box mein text → Enter → box khaali + chat mein text. Email: Sent Items. Tasveer: nayi file khol kar size/format. Activity log mein permission/verification.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 8C commit `5335070`, `main` mein merge `76cc7f6`.

---

### Task: Phase 9 — Memory (short-term, long-term, conversation history, workflows, preferences)

Status: Complete (branch `phase-9-memory`, approval ke baad `main` mein merge)

Admin ke faisle (is phase ke shuru mein): long-term memory **"kahne par + tajweez"** (NOVA sirf "yaad rakho" par ya apne sawal "Ye yaad rakhoon?" ke jawab mein "haan" par yaad rakhta hai — kabhi chupke se nahi), history **90 din** (badal sakte hain), workflows **sirf kholne wale kaam**.

Kaam:
- **Short-term memory** (sirf RAM): pichli 4 baatein AI brain ke liye, "dobara karo" ke liye aakhri command, aur NOVA ka khula sawal — taa ke agla jawab ("haan", "Chrome aur VS Code") usi sawal ka jawab samjha jaye. 30 minute khamoshi, restart, ya "naya topic" par saaf; saath mein "isko" wali pichli file bhi bhool jati hai.
- **Long-term memory (Memory Agent):**
  - "yaad rakho ke meri wife ki birthday 5 March ko hai" → save aur dobara parh kar verify. "ye yaad rakho" → abhi kahi hui baat.
  - Tajweez: "mera naam Ahmed hai", "main Lahore mein rehta hoon", "mujhe chai pasand hai" jaisi baat par NOVA poochta hai "Ye yaad rakhoon? (haan/nahi)" — UI mein Haan/Nahi buttons, awaaz par mic khud khulta hai. "Nahi" ke baad usi session mein dobara nahi poochta.
  - Naam/shehar/kaam/birthday ek hi rehte hain (naya naam purane ki jagah, user ko bataya jata hai). NOVA naam se salam karta hai ("Assalam-o-Alaikum Ahmed!"), "mera naam kya hai" ka seedha jawab.
  - Yaad dilana: "meri biwi ki salgirah kab hai" (hum-maani alfaaz: biwi/wife, salgirah/birthday), "tumhe mere baare mein kya yaad hai".
  - **Passwords, PIN, OTP, card/CNIC/account numbers, keys kabhi yaad nahi** — inkaar. Reminder ("yaad dilana") abhi nahi — saaf bata deta hai.
  - Mutaliqa yaadein local AI ko context ke tor par (sirf jo baat se milti hon, max 5) — data, hidayat nahi.
  - **Bhoolna hamesha poocha jata hai** (dialog mein wahi baatein), kabhi "yaad" nahi rakha jata; "sab bhool jao" high risk.
- **Conversation history:** har command ka record — date, time, request, NOVA ka jawab, actions (agent), ijazat, verification, error, nateeja (ho gaya / nahi hua / ijazat nahi mili / jawab). Awaaz se: "aaj kya kya kiya", "kal maine kya kaha tha", "history mein report dhoondo"; Memory tab mein search + din. **90 din** baad khud mit jati hai (30 din / 1 saal / hamesha — Memory tab se). "Saari history mita do" **high risk** (dialog mein kitni baatein aur kab se kab tak) aur activity log + ijazat ke records bhi mitata hai; screen ki conversation bhi saaf.
- **Workflow memory:** pehli dafa "work start karo" → "Kaun se applications open karoon?" → jawab ("Chrome, VS Code aur WhatsApp") → workflow save aur sab khul jata hai. Agli dafa seedha chalta hai — har qadam normal plan, ijazat aur verification se. Sirf kholne wale qadam: apps (PC par mili hui), websites, code projects, folders, aur volume/brightness ka tay level — delete/bhejna/badalna kabhi nahi. Naam se workflows ("study workflow banao: YouTube aur Downloads folder", "study start karo"), add/remove, list, delete (ijazat se). Na milne wali cheez saaf batai jati hai.
- **Task memory:** "dobara karo" pichla asli kaam dobara (khatre wala ho to phir poochta hai; workflow bhi), "kya kaha" pichla jawab dobara.
- **Preferences:** naam (salam), pasand/napasand (AI ke jawab mein), aur pehle se maujood Settings (search engine, browser, awaaz, history ki muddat). **System memory:** System Profile (Phase 2).
- **UI:** naya **Memory** tab — Yaadein (add, bhool jao, sab mitao), Workflows (Chalao / Badlo / Hatao, naya), History (search, din, ek record mitao, sab mitao, kitni der rakhein), Abhi ki baat-cheet (kya yaad hai, "dobara karo" kya karega, abhi saaf karein). Har mitana UI mein ek dafa aur poochta hai. Memory Agent agents ki list mein.
- **AI brain:** 9 naye intents (rules + LLM): remember_fact, recall_memory, forget_memory, search_history, clear_history, save_workflow, list_workflows, delete_workflow, repeat_last; run_workflow ab chalta hai. LLM agar kisi aam baat ko "explicit" kahe to bhi wo sirf tab save hoti hai jab user ne khud "yaad" kaha ho.

Test:
- Backend automated tests: 550/550 pass (76 naye) — facts/tajweez/secret inkaar, short-term expiry, step resolver, history periods/nateeje, rules aur LLM parsing, explicit save + verify, "haan"/"nahi", naya command sawal ko khatam karta hai, naam se salam, naam badalna, bhoolna (ijazat, high risk), history search/records, saari history mitana (high, sab records + events), 90 din purge aur setting, workflow pehli dafa (pooch kar save + chalana), dobara bina pooche, ghalat cheezein, naam wale workflows add/remove/delete, dobara karo / kya kaha, Memory API (secret wapas echo nahi hota), mutaliqa yaadein hi LLM tak.
- Frontend: 17/17 tests, typecheck aur build successful. Electron app launch: "NOVA Command Center" window, backend health ok, Memory API chal rahi; band karne par backend bhi band.
- AI brain eval (80 commands, 10 naye): sirf rules 75/80 (baqi 4 aam sawal + ek lamba history sawal), **hybrid 80/80** (median 11.2s), sirf LLM 75/80 (median 10.0s). LLM ki do ghaltiyan ("kal" = aaj, "study workflow" naam) prompt/parsing se theek ki — dobara check mein sahi; baqi hybrid mein rules sambhalte hain.
- **Is PC par asli test** (sirf test data "nova9test"/"Nova Tester"; aap ki memory pehle khaali thi):
  - yaad rakhna + verify, "yaad hai ke ... kab hai", naam ki tajweez → haan → "Assalam-o-Alaikum Nova Tester!", "mera naam kya hai", tajweez → nahi (save nahi), ATM pin → inkaar, sab yaadein list.
  - Local AI ko mutaliqa yaad gayi: "aaj raat ke khane mein kya banaun jo mujhe pasand ho" → biryani wala jawab.
  - Bhoolna dialog (medium, yaad nahi rakha ja sakta) → Haan → mit gayi (verify).
  - RAM batao → dobara karo → kya kaha; "aaj kya kya kiya", "history mein nova9test dhoondo", LLM se "pichle hafte maine kaun si files delete ki thi" (24s).
  - "saari history mita do" → high risk dialog ("176 baatein: 2 Oct 08:47 se 19:08 tak ...") → **Nahi** — aap ki history mehfooz.
  - "nova9test workflow chalao" → sawal → "Calculator aur example.com" → save + Calculator khula (verify) + example.com (verify); "nova9test start karo" → bina pooche dobara; "mere workflows dikhao".
  - UI (browser pane): Memory tab ke chaaron hisse, Chalao button se workflow chala, Haan/Nahi buttons, History search aur ek record "Mitao".
  - Test ke baad: test yaadein, workflow aur test ki 37 history records hata diye, short-term saaf, test ke Calculator band (sirf test ke waqt khule hue).

Bugs jo test ke dauran mile aur fix kiye gaye:
- **Asli test mein:** "nova9test meeting wali baat bhool jao" ne do yaadein chun li (dono mein "nova9test" tha; dialog mein dono dikhi thin) — ab sirf sab se zyada milti hui baat chuni jati hai.
- **Asli test mein:** lambi conversation ke baad local AI 45s timeout ho raha tha (pichle lambe jawab context mein jate the) — ab har pichli baat ka sirf shuru ka hissa jata hai (24-33s; PC par anjaan `cmd.exe` CPU le raha tha).
- **Asli test mein:** "dobara karo" ek aam baat ("mujhe ... pasand hai") ko dobara karna samajhta — ab sirf woh command jo chali (ya jis ki ijazat nahi mili thi).
- "dobara karo" ke baad workflow "save nahi" keh deta — ab dobara workflow chalta hai. "kya kaha" pichli command ki jagah le leta — fix. "ye yaad rakho" do dafa kehne par khud "ye yaad rakho" save ho jata — fix. "naya topic" par ijazat maangi ja rahi thi — fix. History search mein purane "history" jawab bhi aa rahe the — fix.
- **Phase 8C ka bug:** local AI se window minimize/maximize mein app ka naam chhoot jata tha (code ghalat jagah tha) — theek, regression test.
- "History mitane" ke dialog mein kuch nazar nahi aata tha — ab kitni baatein aur kab se kab tak.

Maloom hadood (limitations):
- Reminders (waqt par yaad dilana) abhi nahi.
- Tajweez sirf saaf jumlon par (naam, shehar, kaam, birthday, pasand); baqi ke liye "yaad rakho ke ..." kahein.
- History search alfaaz se hai (maane se nahi); Roman Urdu ke mukhtalif hijje ("dhoondo"/"dhundo") alag samjhe ja sakte hain.
- Workflow sirf kholta hai; apps PC par maujood hon to hi (save ke waqt check). Kisi workflow ka naam kisi installed app jaisa ho to workflow pehle.
- Chhota local model kabhi yaadon ko ajeeb jumle mein milata hai — sirf jawab ke alfaaz, koi kaam nahi.

Verification:
- Yaad: save ke baad dobara parhna; bhoolna/mitana: baad mein check ke ab nahi; workflow: save ke baad wahi qadam parhna, har qadam ka apna verify (window/page); history mitana: baad mein ginti 0. Activity log mein sab.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 9 commit `f7013be`, `main` mein merge `8ad40f9`.

---

### Task: Phase 10 — Emotion/Behavior Layer (context analysis, tone adaptation, behavior patterns, personalization)

Status: Complete (branch `phase-10-emotion-behavior`, approval ke baad `main` mein merge)

Admin ke faisle (is phase ke shuru mein): andaza **alfaaz + awaaz** se (awaaz ke numbers kabhi save nahi), andaza **dikhaya jaye** (Settings se band), aadatein **seekhein + tajweez** (sirf "haan" par workflow), jawab ka andaz **khud adapt**.

Kaam:
- **Conversation context analysis (andaza — kabhi pakki baat nahi):**
  - Alfaaz aur jumle: naraazgi ("kitni dafa", "kaam nahi kar raha", "bakwas", "!!", BARE HAROOF), jaldi ("jaldi", "foran"), uljhan ("samajh nahi aaya", "kya matlab", "??"), shukriya/tareef, thakan — Roman Urdu, English, Urdu/Hindi script.
  - Baat-cheet: wahi baat dobara jab pehli dafa kaam nahi hua, pichle 3 mein se 2 kaam nahi hue, foran agli command.
  - Awaaz: bolne ki raftaar (alfaaz/second), zor (dB) aur pitch — **aap ki apni pichli 3+ baaton ke muqable mein** (sirf RAM mein, awaaz aur ye numbers kabhi save nahi). Sirf awaaz se zyada se zyada "shayad ...".
  - Kamzor ishara "neutral" rehta hai; label hamesha "shayad jaldi mein" / "jaldi mein lagte hain" aur wajah ke sath; pichla andaza agli baat mein thora sa rehta hai phir khatam. Andaza kahin save nahi hota (na history, na database).
- **Tone adaptation:** pareshani → "Maaf kijiye." + saaf agla qadam ("Seedha aise kahein, maslan ..." / "dobara karo"); jaldi/thakan → chhota jawab (verify ki lambi baat ki jagah ✓, how-to hint hata), bola gaya jawab aur chhota; uljhan → "(Misaal: ...)"; seedhi chhoti command → bas "ho gaya" bolna. Local AI ke chat jawab ko bhi wahi hidayat. **Haqeeqat kabhi nahi badalti** — kya hua, kya verify hua, kya nahi hua.
- **Response personalization:** jawab ka andaz — Khud adapt (default) / Hamesha chhote / Hamesha tafseel (Settings ya awaaz se: "chhote jawab diya karo", "tafseel se bataya karo", "normal jawab diya karo" — verify ke sath). "shukriya" → "Koi baat nahi, <naam>!" (Phase 9 ka naam).
- **User behavior patterns (aadatein):** kaun si apps/websites/projects kab kholi aur kaun si commands chalti hain — isi PC par, history ki tarah 90 din aur history ke sath mitti hain; NOVA ke apne baare ki commands (bhoolna, history waghera) aadat nahi ginti. "meri aadatein batao", Memory → **Aadatein** (kitni dafa, kitne din, zyada tar subah/shaam...). "meri aadatein bhool jao" — ijazat se.
- **Routine → workflow tajweez:** jo cheezein 3+ alag dinon par ek saath (10 minute ke andar) khulti hain → aik dafa poochta hai "Main ne dekha hai aap aksar subah ... ek saath kholte hain (3 din). Inka 'subah' workflow bana doon? (haan/nahi)" — Haan/Nahi buttons; haan par hi workflow; nahi yaad rehta (us ke hisson ki bhi dobara tajweez nahi); jo workflow mein pehle se ho us ki tajweez nahi; naam kisi maujooda workflow se nahi takrata.
- **UI:** avatar ke neeche "Andaza: shayad jaldi mein (sirf andaza)" (wajah tooltip mein), Live Activity mein Behavior Layer ki line, Settings → **Andaz aur aadatein** (jawab ka andaz + 5 switches), Memory → **Aadatein** (list, routine: "Workflow banao" / "Nahi chahiye", "Aadatein bhool jao"), agents mein Behavior Layer.
- **AI brain:** 3 naye intents (thanks, set_reply_style, show_patterns) rules + LLM; "aadatein bhool jao" bhoolne mein.

Test:
- Backend automated tests: 588/588 pass (38 naye) — alfaaz/Urdu script ke ishare, awaaz ke features (asli sine-wave audio se pitch/zor/raftaar), andaza (hedged, kamzor ishara neutral, sirf awaaz max "shayad", apni pichli awaaz se muqabla, pichla andaza fade), tone (calm/brief/helpful, haqeeqat wahi, ✓ rehta hai), routines (3 din, workflow mein ho to nahi, nahi ke baad hisson ki bhi nahi, 30 din), aadat summary, rules/LLM, API flows (jaldi → chhota jawab + label; label band → phir bhi adapt; andaza band → aam), do dafa nakaami → "Maaf kijiye" + agla qadam, shukriya naam ke sath, jawab ka andaz awaaz se + verify, aadatein record/dikhana/bhoolna (ijazat), routine → haan par workflow, nahi yaad, history mitane par aadatein bhi, chat jawab ko style hint, **awaaz end-to-end: 3 aam baaton ke baad tez boli lambi command → "shayad jaldi mein" aur chhota bola gaya jawab; awaaz ka kuch save nahi**.
- Frontend: 18/18 tests, typecheck aur build successful.
- AI brain eval (86 commands, 6 naye): sirf rules 80/86, **hybrid 85/86** (median 15.1s; ek ghalti "har cheez tafseel se samjhaya karo" — rule add kiya), sirf LLM 83/86 (median 11.0s; teen ghaltiyan hybrid mein rules sambhalte hain).
- **Is PC par asli test:** (sirf test data; pehle aadatein 0 thin)
  - "jaldi se Calculator kholo" → "Calculator khul gaya hai. ✓" (chhota). Bemaani command do dafa (local AI ke zariye) → doosri dafa "... Seedha aise kahein, maslan ...".
  - "samajh nahi aaya, file kaise kholoon" → local AI ka seedha jawab misaal ke sath. "shukriya" → "Koi baat nahi! ...".
  - "chhote jawab diya karo" → Settings mein short (verify) → "normal jawab diya karo" → wapas auto.
  - "meri aadatein batao" → Calculator, usual time. Do pichle din ki test aadatein daal kar "Calculator kholo" + "example.com kholo" → "Main ne dekha hai aap aksar subah Calculator aur example.com ek saath kholte hain (3 din). Inka 'subah' workflow bana doon?" → haan → workflow bana (verify).
  - "meri aadatein bhool jao" → ijazat (medium) → 13 records mit gaye (verify).
  - UI: avatar ke neeche "Andaza: shayad jaldi mein (sirf andaza)", Live Activity mein Behavior Layer ki wajah, Settings → Andaz aur aadatein, Memory → Aadatein.
  - Electron app launch: window, backend aur Behavior API theek; band karne par backend bhi band.
  - Test ke baad: test ki 15 history records aur aadatein hata di, test workflow mitaya, settings pehle jaisi, test ke Calculator band.
  - Awaaz se asli test (mic) browser pane mein mumkin nahi — admin test mein aap karein (automated voice test chal raha hai).

Bugs jo test ke dauran mile aur fix kiye gaye:
- "jaldi se Chrome kholo" mein app ka naam "se Chrome" ban raha tha (purana bug: "jaldi" "jaldi se" se pehle check hota tha) — fix.
- Kamyab command dobara kehna (maslan "Chrome kholo" do dafa) naraazgi gina ja raha tha — ab sirf tab jab pehli dafa kaam nahi hua.
- Chhote jawab mein how-to hint ke sath verify ka nishan bhi hat jata — ab sirf hint hat'ta hai, ✓ rehta hai.
- "aadatein bhool jao" khud ek aadat ban kar record ho jata — NOVA ke apne baare ki commands ab aadat nahi.
- Routine "Workflow banao" kisi purane isi naam ke workflow ko badal sakta tha — ab naam takrata nahi.
- Voice test: NOVA ke bolte waqt mic band rehta hai (sahi) — test ab NOVA ke chup hone ka intezar karta hai.

Maloom hadood (limitations):
- Andaza sirf andaza hai: mazaq ya Urdu ke mukhtalif andaz ko ghalat samajh sakta hai — is liye hamesha "shayad" aur sirf andaz badalta hai, kaam nahi.
- Awaaz ka muqabla sirf usi session mein pichli baaton se (restart par phir se seekhta hai); pehli 3 baaton mein awaaz se kuch nahi (sirf bohat tez raftaar ka kamzor ishara).
- Pitch ka andaza shor wale kamre mein kamzor; is ka wazan kam rakha hai.
- Routine ke liye kam az kam 3 din chahiye; files ki routine abhi nahi (sirf apps, websites, projects).

Verification:
- Jawab ka andaz badalna: Settings dobara parh kar; aadatein bhoolna: baad mein 0 records; routine se bana workflow: workflow save verify (Phase 9). Andaza kuch nahi badalta, is liye us ka verification nahi — sirf dikhaya jata hai.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 10 commit `b02e8d0`, `main` mein merge `4e4e05f`.

---

### Task: Phase 11 — Testing & Logs (automated testing, verification, admin testing, LOGS.md, bug tracking, approval system)

Status: Complete (branch `phase-11-testing-logs`, approval ke baad `main` mein merge)

Admin ke faisle (is phase ke shuru mein): Admin panel ka **Approve LOGS.md mein likhe** (commit/merge phir bhi chat se), LOGS.md mein **rozana khulasa sirf ginti**, error par **mehfooz kaam 1 dafa khud** phir poochna, self-test **start par tez + button par poora**.

Kaam:
- **Admin panel (naya "Admin" tab):** LOGS.md ke har phase ka lifecycle (Implemented → Automated test → Verified → Admin test → Admin approved; problem ho to wapas fix par), README se manual test steps, aur buttons **Test Feature / Approve / Report Problem / Retest** (spec 28).
- **Approval system:** Approve sirf admin ke click + "Haan, approve" par; LOGS.md mein usi phase ka "Admin Test: Complete" aur "Admin Approval: Approved (date, admin ne NOVA Admin panel se approve kiya)" likha jata hai — baqi text bilkul nahi badalta (atomic write). Jis phase ke bug band nahi us ki approval inkaar. Har faisla `approvals` table aur activity log (admin_status) mein. NOVA khud kabhi approve nahi karta.
- **Bug tracking:** admin ki report, command handle karte waqt **crash khud bug** (code ki jagah ke hisaab se aik bug, dobara ho to ginti barhti, band bug dobara khulta), aur **nakaam self-test check** bhi bug. Status: khula → fix → retest → band (ya dobara khula), poori history. Phase ke bug LOGS.md mein us phase ke neeche "Admin bugs:". Bug ke text se secrets chhupaye jate hain.
- **Automated testing:**
  - App ke andar **self-test**: 21 mehfooz checks phase ke hisaab se (database, data folder, system profile, rules brain, local AI tayyar + jawab, awaaz ke models + Urdu awaaz, windows, permission ke qaide, browser, web search, folders, coding tools, Windows settings, WhatsApp/Outlook, tasveer tools, memory, behavior layer, LOGS.md, secrets ka chhupna). Start ke 25 second baad chupchaap tez checks — sirf masla ho to Live Activity aur Admin tab par ● ; poora test (local AI + awaaz) Admin tab se. Har run `test_runs` aur activity log (test_status) mein.
  - Developer ke liye ek command: `scripts/check_all.py` — pyflakes, backend tests, frontend tests, typecheck, build; Roman Urdu khulasa.
- **Verification + error handling (spec 32):** mehfooz, low-risk kaam jis ki ijazat nahi li gayi thi (app/website/project/folder kholna, window, volume/brightness ka tay level) verify na ho to **ek dafa khud dobara** + verify; phir bhi na ho to wajah ke sath "Kya main ek dafa aur koshish karoon? (haan/nahi)". Bhejna, mitana, type/click ya ijazat wala kaam kabhi khud dobara nahi.
- **LOGS.md system activity:** din mein ek dafa (agle din) "System activity (rozana khulasa)" mein **sirf ginti** — commands, kitne hue, nakaam, ijazat, bugs, self-tests. User ke alfaaz, file names, messages kabhi nahi.
- **Activity Log:** filters (Nakaam/errors, Verify nahi hua, Ijazat ke sawal, Inkaar, Tests, Admin) aur search; runtime kaamon ka admin_status ab "not_required" ki jagah sahi.

Test:
- Backend automated tests: 601/601 pass (13 naye + ek awaaz ka regression test) — LOGS.md parhna/likhna (sirf admin wali lines badalti hain), rozana khulasa ek hi dafa, self-test (checks, record, nakaam check → aik bug), problem → fix → retest → approve (khule bug par inkaar, pakka kiye baghair 422, pehle se approved 409), approved phase par problem → approval wapas Pending, LOGS.md na ho to kuch nahi likha jata, crash → aik bug (dobara → ginti barhi, band bug dobara khula), mehfooz kaam 1 dafa khud + phir sawal (haan/nahi), ijazat wala kaam kabhi khud dobara nahi, khulase mein sirf ginti (alfaaz nahi), activity filters, start ka self-test chupchaap.
- Frontend: 19/19 tests, typecheck aur build successful.
- `scripts/check_all.py` khud: pyflakes, backend 601, frontend 19, typecheck, build — sab THEEK (pehli dafa chala to ek bekaar f-string pakri).
- **Is PC par asli test:** 
  - Start ke 25s baad self-test chupchaap chala: 17 theek, 2 info (Brave key nahi, Outlook set nahi) — koi masla nahi, is liye koi alert nahi.
  - Poora self-test (18s): 19 theek, 2 info, 0 nakaam — local AI ne "Chrome kholo" 13.8s mein sahi samjha, Urdu awaaz bani, volume parha, 171 apps, LOGS.md ke 13 tasks.
  - "Test Feature" Phase 8C aur 11 — sirf unhi phases ke checks.
  - **Approval flow alag backend par** (apna data folder aur LOGS.md ki **copy**): Phase 11 par Report Problem → bug #1 khula → Approve inkaar (409, "bug band nahi") → Fix ho gaya → Retest (2 theek) → band → Approve → copy mein "Admin bugs: - #1 (band, ...)" aur "Approved (2026-10-02, admin ne NOVA Admin panel se approve kiya)". **Asli LOGS.md ko haath nahi lagaya** (check kiya).
  - UI: Admin tab — self-test card, aaj ki ginti, har phase ke lifecycle chips (1–10 approved, 11 verified), Phase 11 ke 9 steps, Test Feature/Approve/Report Problem/Retest; Live Activity mein self-test ki lines; Activity Log ka "Tests" filter.
  - Electron app: window, backend aur Admin API (13 phases) theek; band karne par backend band.
  - Retry aur crash bug asli PC par jaan bujh kar nahi karwaye (app ko zabardasti fail karna mehfooz nahi) — automated tests mein cover hain.

Bugs jo test ke dauran mile aur fix kiye gaye:
- **Self-test ne pakra (Phase 10 ka bug):** awaaz ki raftaar/pitch naapne mein "sab se halki 20% awaaz = kamre ka shor" maana jata tha; push-to-talk ke segment mein khamoshi kam ho to awaaz hi shor samjhi jati aur kuch nahi naapa jata — ab sab se oonchi awaaz ke muqable mein (regression test).
- `check_all.py` ne pakra: ek test mein bekaar f-string.
- Rozana khulasa start par foran likha jata to tests mein race — ab self-test ki tarah thori der baad.

Maloom hadood (limitations):
- Approval LOGS.md mein likhi jati hai; commit/merge aap ke chat mein kehne par hi (git NOVA khud nahi chalata).
- Crash bugs sirf command handle karte waqt ke; UI (Electron) ke andar ke errors abhi yahan nahi aate.
- Self-test mehfooz hai — asli app kholna, message bhejna waghera nahi karta; un ke liye manual test steps hain.
- Rozana khulasa sirf jab NOVA chalaya jaye (band PC par nahi likha jata; agli dafa pichle din likh deta hai).

Verification:
- Approve/problem/bug status ke baad LOGS.md dobara parh kar check (tests); self-test ke har check ka nateeja; retry ke baad dobara verify.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

Git:
- Phase 11 commit `9d8be7b`, `main` mein merge `724fe8b`.

---

### Task: Phase 12 — Windows EXE (installer, Windows ke sath start, tray, uninstall)

Status: Complete (branch `phase-12-windows-exe`, approval ke baad `main` mein merge)

Admin ke faisle (is phase ke shuru mein): **sab andar (offline)** installer — app, apna Python aur packages, awaaz ke models; Ollama aur AI model alag (un ka apna installer). Windows ke sath start **pehli dafa pooche** (Silent ya Active, baad mein Settings se badle). Window ka X → **tray mein chhup jaye**, tray se "Band karein". Is PC par alag test folder mein **install + uninstall** test ki ijazat.

Kaam:
- **Installer:** `npm run dist` (desktop/) se ek file `NOVA-Setup-0.12.0.exe` (~790 MB): Electron app + **NOVA ka apna Python** (tested `.venv` se copy — tests/pip/dev tools nahi) + backend + Whisper aur Urdu awaaz ke models. Internet ke baghair install. Build ke waqt `python -m nova --check` (22 zaroori modules) se runtime pakka kiya jata hai.
- **Install:** sirf is user ke liye (admin rights nahi), folder chun sakte hain, Desktop + Start menu shortcut, Apps list mein "NOVA (KN Softic)". Program `…\Programs\NOVA` mein, data alag `%LOCALAPPDATA%\NOVA\data` mein (update par data rehta hai). Development copy pehle ki tarah `data/` istemal karti hai.
- **Pehli dafa setup (wizard):** Salam → Windows start (haan/nahi, Silent ya Active) → Local AI (Ollama install/chal raha/model; "Ollama download page kholo" aur model download **sirf click par**, progress bar) → Awaaz (models maujood) → Tayyar. "Abhi nahi" se chhor sakte hain; sab Settings mein baad mein.
- **Windows ke sath start:** Settings/wizard se on/off → Windows "Run" entry (`NOVA.exe --startup`). **Silent:** sirf tray icon + balloon "Hey NOVA ka intezar" (wake word ke liye mic on). **Active:** window khulti hai aur NOVA bolta hai "Assalam-o-Alaikum. NOVA online hai."
- **Tray:** X dabane par NOVA tray mein (pehli dafa balloon), backend aur sunna chalta rehta hai; tray click → wapas, menu → "NOVA kholo" / "Band karein". Doosri dafa kholne par wahi window aage aati hai.
- **Uninstall:** pehle NOVA ka apna backend band, program + shortcuts + Apps entry + Windows start entry khatam; "NOVA ka data bhi mitayein?" (default Nahi — dobara install par yaadein wapas).
- **Settings → "NOVA ke baare mein":** version, installed/development, program/data/models folder, Python, Windows start registered ya nahi (installed mein folder kholne ke buttons).
- **Self-test:** naya check "Installation aur Windows startup" (models gum = nakaam; start on magar registered nahi = warn). Installed NOVA mein LOGS.md nahi hota — us check ka "info".
- App ka naya icon (orb + N), version 0.12.0.

Test:
- Backend automated tests: 611/611 pass (10 naye) — naye: installed/development configuration, awaaz ke models ki pehchan, setup status, AI model download sirf maangne par (progress 10/40/70/100, activity row), nakaam download aur Ollama band (409), installation ka self-test (pass/fail/warn), runtime build ke filters, `--check`, bana hua runtime khud chalta hai, sust local AI = warn (bug nahi).
- Frontend: 20/20 tests (1 naya — wizard ka double-click), typecheck aur build successful (`scripts/check_all.py` — sab THEEK).
- **Is PC par asli install test** (alag folder `%TEMP%\nova-install-test`, admin ki ijazat se):
  - Installer bana (787 MB), chupchaap install ~6 minute (1.49 GB, 9953 files), Desktop/Start menu shortcut aur Apps entry bani.
  - Installed NOVA ne apne Python se backend chalaya (developer ka Python nahi), data `%LOCALAPPDATA%\NOVA\data`, models andar se, Ollama + qwen3:4b tayyar; "RAM batao" sahi.
  - Poora self-test installed NOVA par: 18 theek; local AI pehli dafa (thanda model) 45s mein jawab nahi — is par fix (neeche).
  - Windows start on → Run entry `"…\NOVA.exe" --startup`; off → entry khatam.
  - `--startup` + Silent → window nahi, sirf tray; Active → window + awaaz "Assalam-o-Alaikum. NOVA online hai." (NOVA_SPEAK 2.3s).
  - X → window chhupi, NOVA aur backend chalte rahe (30s tak har 5s check), tray mein hote hue "RAM batao" ka jawab aaya.
  - Uninstall (38s): folder, shortcuts, Apps entry aur Windows start entry khatam, data rakha gaya (default Nahi), koi NOVA process baqi nahi.
  - **Fixes ke baad naya installer, dusra install test:** install (330s) ke foran baad installer ki copy aur `nova-desktop-updater` folder khatam; pichle test ka data wapas mila (setup ho chuka, history); backend 39s mein install folder ke Python se; self-test "Installation" theek, local AI ne "Chrome kholo" sahi samjha (45.1s — ab warn, nakaam/bug nahi); uninstall (39s) phir saaf, data rakha gaya.
  - Test ke baad saaf kiya: test folder, `%LOCALAPPDATA%\NOVA` (sirf test ka data) — PC par NOVA ka kuch baqi nahi.
  - Setup wizard aur "NOVA ke baare mein" browser preview mein alag (test) backend par — asli settings ko haath nahi lagaya.

Bugs jo test ke dauran mile aur fix kiye gaye:
- **Uninstall ke baad ~787 MB baqi:** electron-builder installer ki poori copy `%LOCALAPPDATA%\nova-desktop-updater` mein rakhta hai (auto-update ke liye) — NOVA mein auto-update nahi, is liye ab install ke foran baad aur uninstall par mita di jati hai.
- **Wizard mein double-click:** "Aage" aur "Shuru karein" ek hi jagah hain — tez double-click se step chhoot kar setup khatam ho jata tha; ab step badalne ke 0.4s tak doosra click nahi ginta (test).
- **Self-test ka local AI check:** thanda model pehli dafa load hone mein 45s se zyada le sakta hai → "nakaam" aur bug ban jata tha; ab 120s tak intezar, phir bhi na aaye to "warn" (bug nahi) (test).
- Pehla icon dhundla/safed dhabba tha — dobara banaya.

Maloom hadood (limitations):
- Installer code-signed nahi — Windows SmartScreen "unknown publisher" keh sakta hai (*More info → Run anyway*).
- Ollama aur AI model installer mein nahi (faisle ke mutabiq); wizard batata hai aur model click par download karta hai.
- Auto-update nahi — naya version dobara install karna hoga (data rehta hai).
- Windows ke sath start sirf installed NOVA mein; development copy mein ye setting sirf save hoti hai.
- Installer bara hai (~790 MB) kyun ke awaaz ke models aur Python andar hain.

Verification:
- Install/uninstall ke baad files, shortcuts, registry (Apps + Run) aur processes check kiye; runtime ka `--check`; self-test ka install check.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-03, admin ne chat mein approve kiya)
