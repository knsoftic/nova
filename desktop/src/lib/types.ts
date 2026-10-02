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
  | "ACTION_EXECUTED"
  | "VERIFICATION_STARTED"
  | "VERIFICATION_PASSED"
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
  | "AI_STATUS";

export type AiMode = "hybrid" | "llm" | "rules";

export interface UserSettings {
  assistant_name: string;
  wake_word: string;
  continuous_listening: boolean;
  startup_mode: "silent" | "active";
  ai_mode: AiMode;
  ai_model: string;
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
  status: "ready" | "unavailable" | "needs_permission" | "done" | "failed" | "skipped";
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
}

declare global {
  interface Window {
    nova?: {
      getInfo: () => Promise<{ appVersion: string; platform: string; backendUrl: string; backendManaged: boolean }>;
    };
  }
}
