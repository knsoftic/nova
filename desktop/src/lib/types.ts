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
  | "TASK_COMPLETED";

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
  data: { assistant_name: string; state: NovaState; version: string; history: NovaEvent[] };
}

export type ServerMessage = NovaEvent | HelloMessage | { type: "pong" } | { type: "ERROR"; message: string };

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export interface ChatMessage {
  id: string;
  role: "user" | "nova";
  text: string;
  timestamp: string;
  failed?: boolean;
}

declare global {
  interface Window {
    nova?: {
      getInfo: () => Promise<{ appVersion: string; platform: string; backendUrl: string; backendManaged: boolean }>;
    };
  }
}
