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
  | "BEHAVIOR_ESTIMATED";

export type AiMode = "hybrid" | "llm" | "rules";

export interface UserSettings {
  assistant_name: string;
  wake_word: string;
  continuous_listening: boolean;
  startup_mode: "silent" | "active";
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
      getInfo: () => Promise<{ appVersion: string; platform: string; backendUrl: string; backendManaged: boolean }>;
      /** Bring the NOVA window to the front (e.g. when it needs the user's permission). */
      attention: () => Promise<void>;
    };
  }
}
