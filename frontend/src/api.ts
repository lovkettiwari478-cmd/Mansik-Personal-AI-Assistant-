/* MANISK API client — same-origin fetch with CSRF double-submit,
 * typed responses, SSE chat streaming. */

export class ApiError extends Error {
  code: string;
  status: number;
  requestId?: string;

  constructor(message: string, code: string, status: number, requestId?: string) {
    super(message);
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)mansik_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function handle(r: Response): Promise<any> {
  let body: any = null;
  try {
    body = await r.json();
  } catch {
    /* non-JSON */
  }
  if (!r.ok) {
    const err = body?.error;
    throw new ApiError(err?.message || r.statusText || "Request failed", err?.code || "error", r.status, err?.request_id);
  }
  return body;
}

export async function api<T = any>(
  path: string,
  options: { method?: string; body?: any; form?: FormData } = {},
): Promise<T> {
  const method = options.method || (options.body || options.form ? "POST" : "GET");
  const headers: Record<string, string> = {};
  if (method !== "GET" && method !== "HEAD") headers["X-CSRF-Token"] = csrfToken();
  if (options.body) headers["Content-Type"] = "application/json";

  const r = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: options.form ?? (options.body ? JSON.stringify(options.body) : undefined),
  });
  return handle(r);
}

/* Chat SSE streaming via fetch + ReadableStream (POST with CSRF). */
export async function streamChat(
  message: string,
  conversationId: string | null,
  onEvent: (ev: any) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
    credentials: "same-origin",
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  });
  if (!r.ok) {
    await handle(r); // throws ApiError
    return;
  }
  const reader = r.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (chunk.startsWith("data: ")) {
        try {
          onEvent(JSON.parse(chunk.slice(6)));
        } catch {
          /* skip malformed */
        }
      }
    }
  }
}

/* -------- typed helpers -------- */

export interface User {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

export const authApi = {
  register: (email: string, password: string, displayName: string) =>
    api<{ user: User }>("/api/auth/register", { body: { email, password, display_name: displayName } }),
  login: (email: string, password: string) =>
    api<{ user: User }>("/api/auth/login", { body: { email, password } }),
  logout: () => api("/api/auth/logout", { method: "POST" }),
  me: () => api<{ user: User }>("/api/auth/me"),
  changePassword: (current: string, next: string) =>
    api("/api/auth/change-password", { body: { current_password: current, new_password: next } }),
  sessions: () => api("/api/auth/sessions"),
  revokeSession: (id: string) => api(`/api/auth/sessions/${id}`, { method: "DELETE" }),
  logoutAll: () => api("/api/auth/logout-all", { method: "POST" }),
};

export const statusApi = {
  health: () => api("/api/health"),
  status: () => api("/api/status"),
  tools: () => api("/api/tools"),
  integrations: () => api("/api/integrations"),
};

export const taskApi = {
  list: (status?: string) => api(`/api/tasks${status ? `?status=${status}` : ""}`),
  create: (body: any) => api("/api/tasks", { body }),
  update: (id: string, body: any) => api(`/api/tasks/${id}`, { method: "PATCH", body }),
  remove: (id: string) => api(`/api/tasks/${id}`, { method: "DELETE" }),
};

export const memoryApi = {
  list: (kind?: string) => api(`/api/memories${kind ? `?kind=${kind}` : ""}`),
  create: (body: any) => api("/api/memories", { body }),
  update: (id: string, body: any) => api(`/api/memories/${id}`, { method: "PATCH", body }),
  remove: (id: string) => api(`/api/memories/${id}`, { method: "DELETE" }),
  search: (query: string) => api("/api/memories/search", { body: { query } }),
};

export const calendarApi = {
  list: (days = 60) => api(`/api/calendar?days=${days}`),
  create: (body: any) => api("/api/calendar", { body }),
  update: (id: string, body: any) => api(`/api/calendar/${id}`, { method: "PATCH", body }),
  remove: (id: string) => api(`/api/calendar/${id}`, { method: "DELETE" }),
};

export const automationApi = {
  list: () => api("/api/automations"),
  create: (body: any) => api("/api/automations", { body }),
  update: (id: string, body: any) => api(`/api/automations/${id}`, { method: "PATCH", body }),
  remove: (id: string) => api(`/api/automations/${id}`, { method: "DELETE" }),
  runs: (id: string) => api(`/api/automations/${id}/runs`),
};

export const fileApi = {
  list: () => api("/api/files"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api("/api/files", { form });
  },
  remove: (id: string) => api(`/api/files/${id}`, { method: "DELETE" }),
};

export const securityApi = {
  permissions: () => api("/api/security/permissions"),
  setPermission: (scope: string, allowed: boolean, note = "") =>
    api("/api/security/permissions", { body: { scope, allowed, note } }),
  revokePermission: (scope: string) => api(`/api/security/permissions/${scope}`, { method: "DELETE" }),
  emergencyStop: (enabled: boolean) =>
    api("/api/security/emergency-stop", { body: { enabled } }),
  emergencyStopStatus: () => api("/api/security/emergency-stop"),
};

export const settingsApi = {
  get: () => api("/api/settings"),
  patch: (body: any) => api("/api/settings", { method: "PATCH", body }),
};

export const activityApi = {
  list: (category?: string) => api(`/api/activity?limit=200${category ? `&category=${category}` : ""}`),
};

export const conversationApi = {
  list: () => api("/api/conversations"),
  messages: (id: string) => api(`/api/conversations/${id}/messages`),
  remove: (id: string) => api(`/api/conversations/${id}`, { method: "DELETE" }),
};

export const notificationApi = {
  list: () => api("/api/notifications"),
  markRead: (id: string) => api(`/api/notifications/${id}/read`, { method: "POST" }),
  markAllRead: () => api("/api/notifications/read-all", { method: "POST" }),
};

export const graphApi = {
  entities: () => api("/api/graph/entities"),
  createEntity: (body: any) => api("/api/graph/entities", { body }),
  createRelation: (body: any) => api("/api/graph/relations", { body }),
  removeEntity: (id: string) => api(`/api/graph/entities/${id}`, { method: "DELETE" }),
};

export const confirmationApi = {
  pending: () => api("/api/confirmations/pending"),
  approve: (id: string) => api(`/api/confirmations/${id}/approve`, { method: "POST" }),
  deny: (id: string) => api(`/api/confirmations/${id}/deny`, { method: "POST" }),
};

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
