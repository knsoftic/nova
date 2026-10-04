export type NovaState =
  | "IDLE"
  | "LISTENING"
  | "THINKING"
  | "PLANNING"
  | "WORKING"
  | "WAITING_FOR_PERMISSION"
  | "VERIFYING"
  | "COMPLETED"
  | "ERROR";

export type EventType =
  | "SYSTEM_READY"
  | "STATE_CHANGED"
  | "NOVA_LISTENING"
  | "NOVA_THINKING"
  | "TASK_STARTED"
  | "INTENT_DETECTED"
  | "AGENT_STARTED"
  | "AGENT_WORKING"
  | "PERMISSION_REQUIRED"
  | "PERMISSION_DECIDED"
  | "ACTION_EXECUTED"
  | "VERIFICATION_STARTED"
  | "VERIFICATION_PASSED"
  | "VERIFICATION_FAILED"
  | "NOVA_RESPONSE"
  | "TASK_FAILED"
  | "TASK_COMPLETED"
  | "DISCOVERY_STARTED"
  | "DISCOVERY_COMPLETED"
  | "DISCOVERY_FAILED"
  | "SETTINGS_CHANGED"
  | "PLAN_CREATED"
  | "STEP_COMPLETED"
  | "AI_FALLBACK"
  | "AI_STATUS"
  | "VOICE_STATUS"
  | "VOICE_TRANSCRIBED"
  | "WAKE_WORD_DETECTED"
  | "NOVA_SPEAK"
  | "MEMORY_CHANGED"
  | "BEHAVIOR_ESTIMATED"
  | "SELF_TEST"
  | "BUG_LOGGED"
  | "ADMIN_DECISION"
  | "RETRY"
  | "SETUP_PROGRESS"
  | "PEERS_CHANGED"
  | "REMOTE_TASK";

export interface SelfTestResult {
  id: string;
  phase: string;
  name: string;
  status: "pass" | "info" | "warn" | "fail";
  detail: string;
  ms: number;
}

export interface TestRun {
  id: number;
  scope: string;
  passed: number;
  warned: number;
  failed: number;
  results: SelfTestResult[];
  started_at?: string;
}

export type BugStatus = "open" | "fixed" | "closed" | "reopened";

export interface Bug {
  id: number;
  created_at: string;
  updated_at: string;
  phase: string | null;
  title: string;
  details: string | null;
  source: "admin" | "automatic" | "self_test";
  status: BugStatus;
  occurrences: number;
  task_id: string | null;
  history: { at: string; status: string; by: string; note: string }[];
}

/** A development phase from LOGS.md with its lifecycle (spec: Implemented -> ... -> Admin approved). */
export interface AdminFeature {
  phase: string;
  title: string;
  status: string;
  admin_test: string;
  admin_approval: string;
  approved: boolean;
  automated_test: boolean;
  self_test: { ran: boolean; ok: boolean; failed: number; results: SelfTestResult[] };
  steps: string[];
  bugs_active: number;
  bugs_total: number;
  stage: "implemented" | "automated_test" | "verified" | "admin_tested" | "approved" | "problem";
}

export interface DaySummary {
  date: string;
  counts: Record<string, number>;
  line: string;
  logs_md: boolean;
}

export type ActivityKind = "" | "failed" | "unverified" | "permission" | "denied" | "tests" | "admin";

export type AiMode = "hybrid" | "llm" | "rules";

export interface UserSettings {
  assistant_name: string;
  wake_word: string;
  continuous_listening: boolean;
  startup_mode: "silent" | "active";
  /** Start NOVA when Windows starts (installed NOVA only; applied by the desktop app). */
  start_with_windows: boolean;
  /** The first-run setup was completed or skipped. */
  setup_done: boolean;
  ai_mode: AiMode;
  ai_model: string;
  stt_language: "ur" | "hi" | "en" | "auto";
  tts_voice: string;
  speak_responses: "voice_only" | "always" | "never";
  search_engine: "google" | "bing" | "duckduckgo";
  browser_channel: "chrome" | "msedge";
  project_folders: string[];
  /** Conversation history is deleted after this many days; 0 = kept until the user deletes it. */
  history_days: 30 | 90 | 365 | 0;
  reply_style: "auto" | "short" | "detailed";
  emotion_awareness: boolean;
  voice_signals: boolean;
  show_estimate: boolean;
  learn_patterns: boolean;
  suggest_routines: boolean;
  /** Multi-PC (Phase 13): off until turned on; only works on a Private network. */
  multi_pc: boolean;
  /** The name other PCs see ("" = the Windows computer name). */
  pc_name: string;
  /** OpenAI (Phase 13C, optional, needs a saved key): who turns speech into text / which model is the brain. */
  stt_engine: "auto" | "openai" | "local";
  llm_provider: "auto" | "openai" | "ollama";
  openai_model: string;
  openai_stt_model: string;
}

export interface OpenAIStatus {
  configured: boolean;
  key_masked: string | null;
  llm_active: "openai" | "ollama";
  llm_model: string;
  stt_active: "openai" | "local";
  stt_model: string | null;
  llm_error: string | null;
  stt_error: string | null;
}

/** NOVA's estimate of how the user is communicating - only an estimate, never stored. */
export interface BehaviorEstimate {
  state: "frustrated" | "hurried" | "confused" | "positive" | "tired";
  confidence: number;
  label: string;
  reasons: string[];
}

export interface HabitPatterns {
  learning: boolean;
  events: number;
  items: { kind: "app" | "website" | "project"; target: string; count: number; days: number; usual_time: string }[];
  commands: { intent: string; count: number }[];
  routines: { key: string; name: string; labels: string[]; days: number; hour: number }[];
}

/** Something the user asked NOVA to remember (or said "haan" to). Slots hold one value (a new name replaces the old). */
export interface MemoryFact {
  id: number;
  text: string;
  slot: "name" | "city" | "work" | "birthday" | null;
  value: string | null;
  source: string;
  created_at: string;
  updated_at: string;
  uses: number;
  last_used: string | null;
}

export interface WorkflowStep {
  kind: "app" | "website" | "project" | "folder" | "setting";
  value: string;
  label: string;
  setting?: string;
}

export interface Workflow {
  id: number;
  name: string;
  steps: WorkflowStep[];
  created_at: string;
  updated_at: string;
  runs: number;
  last_run: string | null;
}

export type HistoryOutcome = "done" | "failed" | "denied" | "answered" | "not_understood";
export type HistoryPeriod = "" | "today" | "yesterday" | "week" | "month";

/** One searchable conversation record (spec: date, time, task, request, response, result, permission, action, error, status). */
export interface HistoryRecord {
  task_id: string;
  date: string;
  time: string;
  source: string;
  request: string;
  response: string | null;
  intent: string | null;
  actions: string[];
  permission: string;
  verification: string;
  error: string | null;
  outcome: HistoryOutcome;
}

/** The current conversation (RAM only, cleared after a pause). */
export interface ShortTermMemory {
  turns: { user: string; assistant: string }[];
  pending: string | null;
  last_command: string | null;
  idle_reset_min: number;
  resets_in_s: number | null;
}

/** Someone the Communication Agent may message (added by the user only). Phone: international digits. */
export interface Contact {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
}

/** A folder the File/Coding agents may use. */
export interface FileRoot {
  name: string;
  path: string;
  kind: "folder" | "projects";
}

/** Web search setup. The Brave key itself never comes back from the backend — only a masked hint. */
export interface WebStatus {
  search_provider: "brave" | "wikipedia";
  brave_configured: boolean;
  brave_key_masked: string | null;
  search_engine: UserSettings["search_engine"];
  browser_channel: UserSettings["browser_channel"];
}

export interface AiStatus {
  mode: AiMode;
  model: string;
  model_ready: boolean;
  llm_in_use: boolean;
  ollama: { reachable: boolean; version: string | null; models: string[]; error: string | null };
  /** Which model answers: OpenAI (with a key) or the local Ollama model. */
  llm_provider?: "openai" | "ollama";
  last_provider: string | null;
  last_latency_ms: number | null;
}

export interface PlanStepSummary {
  id: number;
  agent: string;
  action: string;
  risk: "low" | "medium" | "high";
  status: "ready" | "unavailable" | "needs_permission" | "denied" | "done" | "failed" | "skipped";
  permission?: "approved" | "rule" | "denied" | "timeout" | null;
  description: string;
  intent: string;
  available_from_phase: number | null;
}

/** One row of the persisted, structured activity log (spec section 30). */
export interface ActivityRecord {
  id: number;
  date: string;
  time: string;
  task_id: string;
  task_name: string;
  agent: string;
  action: string;
  permission_status: string;
  execution_status: string;
  test_status: string;
  verification_status: string;
  admin_status: string;
  error: string | null;
  final_result: string | null;
}

export interface DriveInfo {
  mountpoint: string;
  filesystem: string | null;
  total_bytes: number;
  free_bytes: number;
}

export interface AppEntry {
  name: string;
  version: string | null;
  publisher: string | null;
  sources: string[];
  app_id: string | null;
  executable: string | null;
}

export interface Recommendation {
  key: string;
  value: string;
  reason: string;
  auto_applied: boolean;
}

export interface SystemProfile {
  scanned_at: string;
  scan_duration_ms: number;
  platform: string;
  cpu: { name: string | null; manufacturer: string | null; cores: number | null; threads: number | null; max_clock_mhz: number | null };
  ram_total_bytes: number | null;
  gpus: { name: string; memory_bytes: number | null; driver_version: string | null; vendor: string | null; dedicated: boolean | null }[];
  drives: DriveInfo[];
  windows: {
    caption: string | null;
    version: string | null;
    build: string | null;
    display_version: string | null;
    architecture: string | null;
    computer_name: string | null;
    manufacturer: string | null;
    model: string | null;
  };
  microphones: { name: string }[];
  speakers: { name: string }[];
  cameras: string[];
  displays: { name: string; primary: boolean; width: number | null; height: number | null }[];
  network: { name: string; is_up: boolean; ipv4: string[] }[];
  network_connected: boolean;
  apps: AppEntry[];
  browsers: { name: string; executable: string | null; is_default: boolean }[];
  running_apps: { name: string; title: string | null; pid: number }[];
  startup_items: { name: string; location: string; command: string | null }[];
  services: { name: string; display_name: string | null; status: string | null; start_type: string | null }[];
  permissions: { is_elevated: boolean; user_is_admin: boolean };
  recommendations: Recommendation[];
  errors: string[];
}

export interface LiveStats {
  cpu_percent: number;
  ram_total_bytes: number;
  ram_available_bytes: number;
  ram_percent: number;
  drives: DriveInfo[];
  uptime_seconds: number;
}

export interface NovaEvent {
  type: EventType;
  timestamp: string;
  task_id: string | null;
  agent: string | null;
  message: string | null;
  data: Record<string, unknown>;
}

export interface HelloMessage {
  type: "HELLO";
  data: {
    assistant_name: string;
    state: NovaState;
    version: string;
    voice_active: boolean;
    settings: UserSettings;
    history: NovaEvent[];
  };
}

export type ServerMessage = NovaEvent | HelloMessage | { type: "pong" } | { type: "ERROR"; message: string };

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export interface ChatMessage {
  id: string;
  role: "user" | "nova";
  text: string;
  timestamp: string;
  failed?: boolean;
  /** For NOVA replies: who understood the command and the steps that were planned. */
  provider?: string;
  steps?: PlanStepSummary[];
  /** User message that came from speech recognition. */
  voice?: boolean;
  /** NOVA asked something ("Ye yaad rakhoon?"): one-tap answers. */
  quickReplies?: string[];
}

export type Risk = "low" | "medium" | "high";

export interface PermissionItem {
  step_id: number;
  intent: string;
  description: string;
  risk: Risk;
  reasons: string[];
  target: string | null;
  scope: string;
  rememberable: boolean;
  /** Shown, not spoken: the diff, organize plan or command that will run. */
  preview?: string | null;
}

export interface PermissionRequest {
  id: string;
  task_id: string;
  items: PermissionItem[];
  max_risk: Risk;
  question: string;
  timeout_s: number;
  source: string;
  rememberable: boolean;
  /** Client-side: when it arrived, for the countdown. */
  received_at?: number;
}

export interface PermissionRule {
  id: number;
  intent: string;
  scope: string;
  description: string;
  created_at: string;
  uses: number;
  last_used: string | null;
}

export interface VoiceStatus {
  stt: { model: string; language: string; downloaded: boolean; loaded: boolean; error: string | null };
  tts: { voice: string; available: boolean; voices: { id: string; label: string }[] };
  speak_responses: "voice_only" | "always" | "never";
  continuous_listening: boolean;
  wake_word: string;
}

declare global {
  interface Window {
    nova?: {
      getInfo: () => Promise<{
        appVersion: string;
        platform: string;
        backendUrl: string;
        backendManaged: boolean;
        /** An installed NOVA (not a development copy). */
        packaged?: boolean;
        /** Windows started NOVA at login. */
        launchedAtLogin?: boolean;
      }>;
      /** Bring the NOVA window to the front (e.g. when it needs the user's permission). */
      attention: () => Promise<void>;
      /** Register/unregister "start with Windows" (installed NOVA only). */
      setStartup?: (openAtLogin: boolean) => Promise<{ applied: boolean; reason?: string }>;
      /** Open NOVA's data or program folder in Explorer. */
      openFolder?: (which: "data" | "program") => Promise<string>;
    };
  }
}

/** First-run setup and "about this installation" (Phase 12). */
export interface SetupStatus {
  install: {
    version: string;
    packaged: boolean;
    program_dir: string;
    data_dir: string;
    models_dir: string;
    python: string;
    startup_registered: boolean;
    startup_command: string | null;
    voice_models: { whisper: boolean; piper: boolean };
    logs_md: boolean;
  };
  ollama: { installed: boolean; reachable: boolean; model: string; model_ready: boolean; pulling: boolean };
  setup_done: boolean;
  start_with_windows: boolean;
  startup_mode: "silent" | "active";
  continuous_listening: boolean;
}

export interface SetupProgress {
  percent: number | null;
  message: string;
  done?: boolean;
  ok?: boolean;
}

/** Multi-PC (Phase 13): this PC, the network, PCs found nearby and paired PCs. */
export interface PcNetwork {
  ip: string;
  alias: string;
  category: string;
  name: string;
  private: boolean;
}

export interface FoundPc {
  id: string;
  name: string;
  host: string;
  port: number;
  version: string;
  /** It is showing a code and waiting to be joined. */
  pairing: boolean;
}

export interface PairedPc {
  id: string;
  name: string;
  host: string;
  port: number;
  online: boolean;
  /** THIS PC lets that PC run tasks here. */
  remote_allowed: boolean;
  /** That PC lets this PC run tasks there (last known; null = not known yet). */
  allows_us: boolean | null;
  paired_at: string;
  last_seen: string | null;
}

export interface PcsStatus {
  this: { id: string; name: string; version: string; port: number | null };
  enabled: boolean;
  running: boolean;
  reason: string | null;
  networks: PcNetwork[];
  pairing: { code: string; expires_in: number } | null;
  found: FoundPc[];
  peers: PairedPc[];
}
