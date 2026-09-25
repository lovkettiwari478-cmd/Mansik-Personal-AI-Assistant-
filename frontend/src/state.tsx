/* Global state: auth context, toasts, notifications. */

import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import { api, authApi, notificationApi, User } from "./api";

/* ---------- toasts ---------- */

interface Toast {
  id: number;
  message: string;
  kind: "info" | "error" | "success";
}

const ToastCtx = createContext<{
  toasts: Toast[];
  push: (message: string, kind?: Toast["kind"]) => void;
}>({ toasts: [], push: () => {} });

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: string, kind: Toast["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);
  return (
    <ToastCtx.Provider value={{ toasts, push }}>
      {children}
      <div className="toast-wrap">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>{t.message}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

/* ---------- auth ---------- */

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthCtx = createContext<AuthState>(null as any);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const r = await authApi.me();
      setUser(r.user);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const r = await authApi.login(email, password);
    setUser(r.user);
  }, []);

  const register = useCallback(async (email: string, password: string, displayName: string) => {
    const r = await authApi.register(email, password, displayName);
    setUser(r.user);
  }, []);

  const logout = useCallback(async () => {
    try { await authApi.logout(); } finally { setUser(null); }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout, refresh }),
    [user, loading, login, register, logout, refresh],
  );
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

/* ---------- system status (provider/tool availability) ---------- */

interface SysStatus {
  aiConfigured: boolean;
  aiModel: string | null;
  loaded: boolean;
  refresh: () => Promise<void>;
}

const StatusCtx = createContext<SysStatus>(null as any);

export function StatusProvider({ children }: { children: React.ReactNode }) {
  const [aiConfigured, setAiConfigured] = useState(false);
  const [aiModel, setAiModel] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await api<any>("/api/status");
      setAiConfigured(r.ai_provider?.configured ?? false);
      setAiModel(r.ai_provider?.model ?? null);
    } catch {
      setAiConfigured(false);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const value = useMemo(() => ({ aiConfigured, aiModel, loaded, refresh }), [aiConfigured, aiModel, loaded, refresh]);
  return <StatusCtx.Provider value={value}>{children}</StatusCtx.Provider>;
}

export const useStatus = () => useContext(StatusCtx);

/* ---------- notifications ---------- */

export function useNotifications() {
  const [notifications, setNotifications] = useState<any[]>([]);
  const [unread, setUnread] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const r = await notificationApi.list();
      setNotifications(r.notifications);
      setUnread(r.unread);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);

  return { notifications, unread, refresh };
}
