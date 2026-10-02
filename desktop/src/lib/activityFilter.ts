import type { EventType, NovaEvent } from "./types";

export type ActivityFilter = "all" | "tasks" | "agents" | "system" | "errors";

export const ACTIVITY_FILTERS: { id: ActivityFilter; label: string }[] = [
  { id: "all", label: "Sab" },
  { id: "tasks", label: "Tasks" },
  { id: "agents", label: "Agents" },
  { id: "system", label: "System" },
  { id: "errors", label: "Errors" },
];

const CATEGORY: Record<Exclude<ActivityFilter, "all">, EventType[]> = {
  tasks: [
    "TASK_STARTED",
    "NOVA_THINKING",
    "INTENT_DETECTED",
    "PLAN_CREATED",
    "STEP_COMPLETED",
    "NOVA_RESPONSE",
    "TASK_COMPLETED",
    "TASK_FAILED",
  ],
  agents: [
    "AGENT_STARTED",
    "AGENT_WORKING",
    "ACTION_EXECUTED",
    "PERMISSION_REQUIRED",
    "VERIFICATION_STARTED",
    "VERIFICATION_PASSED",
  ],
  system: [
    "SYSTEM_READY",
    "DISCOVERY_STARTED",
    "DISCOVERY_COMPLETED",
    "DISCOVERY_FAILED",
    "SETTINGS_CHANGED",
    "NOVA_LISTENING",
    "AI_STATUS",
    "AI_FALLBACK",
  ],
  errors: ["TASK_FAILED", "DISCOVERY_FAILED"],
};

export function matchesActivity(event: NovaEvent, filter: ActivityFilter, agent: string | null = null): boolean {
  if (agent && event.agent !== agent) return false;
  return filter === "all" || CATEGORY[filter].includes(event.type);
}
