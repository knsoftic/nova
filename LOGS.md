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
