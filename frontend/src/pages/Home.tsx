/* Home — the MANISK command center.
 * Real backend data only: greeting, AI status, today's tasks, upcoming
 * events, memory indicator, automations, recent activity, quick actions
 * and data-derived suggestions. No fake statistics. */

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmtDate } from "../api";
import { useAuth } from "../state";
import { Badge, EmptyState, Loading } from "../components/ui";
import Layout from "../components/Layout";
import Orb from "../components/Orb";

interface Summary {
  greeting: string;
  user_name: string;
  local_time: string;
  timezone: string;
  assistant_name: string;
  ai: { configured: boolean; model: string | null };
  emergency_stop: boolean;
  memory_enabled: boolean;
  tasks: {
    open: number; due_today: number; overdue: number;
    next: { id: string; title: string; priority: string; status: string; due_at: string | null }[];
  };
  events: { id: string; title: string; starts_at: string; location: string }[];
  memory_count: number;
  unread_notifications: number;
  automations_active: number;
  pending_confirmations: number;
  recent_activity: { id: string; category: string; action: string; created_at: string }[];
}

export default function HomePage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      try {
        setSummary(await api<Summary>("/api/home/summary"));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading || !summary) return <Layout title="Home"><Loading /></Layout>;

  const dateStr = new Date(summary.local_time).toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric",
  });
  const timeStr = new Date(summary.local_time).toLocaleTimeString(undefined, {
    hour: "2-digit", minute: "2-digit",
  });

  const suggestions: { label: string; to?: string; chat?: string }[] = [];
  if (summary.tasks.overdue > 0) {
    suggestions.push({ label: `⚠ ${summary.tasks.overdue} overdue task${summary.tasks.overdue > 1 ? "s" : ""} — review now`, to: "/tasks" });
  }
  if (summary.tasks.due_today > 0) {
    suggestions.push({ label: `◆ ${summary.tasks.due_today} task${summary.tasks.due_today > 1 ? "s" : ""} due today`, to: "/tasks" });
  }
  if (summary.events.length > 0) {
    suggestions.push({
      label: `▤ Next: ${summary.events[0].title} · ${fmtDate(summary.events[0].starts_at)}`,
      to: "/calendar",
    });
  }
  if (!summary.ai.configured) {
    suggestions.push({ label: "⬡ Connect an AI provider to unlock full conversation", to: "/integrations" });
  }
  if (summary.memory_count === 0 && summary.memory_enabled) {
    suggestions.push({ label: "◉ Tell me something to remember about you", chat: "remember that " });
  }
  if (summary.pending_confirmations > 0) {
    suggestions.push({ label: `⛨ ${summary.pending_confirmations} action${summary.pending_confirmations > 1 ? "s" : ""} awaiting your confirmation`, to: "/security" });
  }

  return (
    <Layout title="Home" subtitle="Command center">
      {/* ---- hero ---- */}
      <div className="home-hero">
        <Orb state={summary.ai.configured ? "idle" : "idle"} size={72} />
        <div className="grow">
          <div className="home-greeting">
            {summary.greeting}, <span className="home-name">{user?.display_name?.split(" ")[0]}</span>
          </div>
          <div className="home-date">{dateStr} · {timeStr} <span className="faint">({summary.timezone})</span></div>
          <div className="row wrap mt-8" style={{ gap: 7 }}>
            <Badge kind={summary.ai.configured ? "success" : "warning"}>
              {summary.ai.configured ? `AI · ${summary.ai.model}` : "Local Mode"}
            </Badge>
            {summary.memory_enabled
              ? <Badge kind="info">◉ {summary.memory_count} memories</Badge>
              : <Badge>◉ memory off</Badge>}
            {summary.automations_active > 0 && <Badge kind="accent">⚡ {summary.automations_active} active automation{summary.automations_active > 1 ? "s" : ""}</Badge>}
            {summary.emergency_stop && <Badge kind="danger">🛑 EMERGENCY STOP</Badge>}
          </div>
        </div>
      </div>

      {summary.emergency_stop && (
        <div className="estop active mt-14" role="alert">
          <div className="row between">
            <div className="grow">
              <strong style={{ color: "var(--danger)" }}>Emergency stop is active.</strong>
              <div className="small muted">All tool execution and automations are halted.</div>
            </div>
            <Link to="/security" className="btn small danger">Release</Link>
          </div>
        </div>
      )}

      {/* ---- quick actions ---- */}
      <div className="grid cols-3 mt-14" style={{ gap: 10 }}>
        {[
          { icon: "❖", label: "Ask MANISK", to: "/chat" },
          { icon: "✓", label: "New task", to: "/chat", state: { draft: "create task " } },
          { icon: "▤", label: "Schedule", to: "/calendar" },
        ].map((qa, i) => (
          <div key={i} className="quick-action" style={{ animationDelay: `${i * 40}ms` }}
               onClick={() => navigate(qa.to!, qa.state as any)}>
            <span className="qa-icon" aria-hidden>{qa.icon}</span>
            {qa.label}
          </div>
        ))}
      </div>

      {/* ---- suggestions (derived from real data) ---- */}
      {suggestions.length > 0 && (
        <div className="row wrap mt-14" style={{ gap: 8 }}>
          {suggestions.slice(0, 4).map((s, i) => (
            <span key={i} className="suggestion clickable"
                  onClick={() => s.to ? navigate(s.to) : navigate("/chat", { state: { draft: s.chat } })}>
              {s.label}
            </span>
          ))}
        </div>
      )}

      {/* ---- stat strip ---- */}
      <div className="grid cols-3 mt-14">
        <div className="stat">
          <div className="stat-label">Open tasks</div>
          <div className="stat-value">{summary.tasks.open}</div>
          <div className="stat-hint">
            {summary.tasks.overdue > 0
              ? <span style={{ color: "var(--danger)" }}>{summary.tasks.overdue} overdue</span>
              : summary.tasks.due_today > 0 ? `${summary.tasks.due_today} due today` : "nothing overdue"}
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Upcoming events</div>
          <div className="stat-value">{summary.events.length}</div>
          <div className="stat-hint">next 7 days</div>
        </div>
        <div className="stat">
          <div className="stat-label">Memories</div>
          <div className="stat-value">{summary.memory_count}</div>
          <div className="stat-hint">{summary.memory_enabled ? "memory enabled" : "memory disabled"}</div>
        </div>
      </div>

      {/* ---- tasks + events ---- */}
      <div className="grid cols-2 mt-14">
        <div className="card">
          <div className="row between mb-14">
            <div className="card-title">Up next</div>
            <Link to="/tasks" className="small">All tasks →</Link>
          </div>
          {summary.tasks.next.length === 0 ? (
            <EmptyState icon="✓" title="Nothing pending" hint="Ask MANISK to create tasks in chat." />
          ) : summary.tasks.next.map((t) => {
            const overdue = t.due_at && new Date(t.due_at) < new Date() && t.status !== "done";
            return (
              <div key={t.id} className="list-item">
                <div className={`prio ${t.priority}`} />
                <div className="grow">
                  <div style={{ fontWeight: 600 }}>{t.title}</div>
                  <div className="small faint">
                    {t.due_at ? `due ${fmtDate(t.due_at)}` : "no due date"} · {t.priority}
                  </div>
                </div>
                {overdue && <Badge kind="danger">overdue</Badge>}
              </div>
            );
          })}
        </div>

        <div className="card">
          <div className="row between mb-14">
            <div className="card-title">Next events</div>
            <Link to="/calendar" className="small">Calendar →</Link>
          </div>
          {summary.events.length === 0 ? (
            <EmptyState icon="▤" title="No events this week" />
          ) : summary.events.slice(0, 5).map((e) => (
            <div key={e.id} className="list-item">
              <div className="grow">
                <div style={{ fontWeight: 600 }}>{e.title}</div>
                <div className="small faint">
                  {fmtDate(e.starts_at)}{e.location ? ` · ${e.location}` : ""}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ---- recent activity (real audit rows) ---- */}
      <div className="card mt-14">
        <div className="row between mb-14">
          <div className="card-title">Recent activity</div>
          <Link to="/activity" className="small">Full audit →</Link>
        </div>
        {summary.recent_activity.length === 0 ? (
          <EmptyState icon="≡" title="No activity yet" />
        ) : summary.recent_activity.map((a) => (
          <div key={a.id} className={`feed-item ${a.category}`}>
            <div className="row wrap">
              <Badge kind={a.category === "security" ? "warning" : a.category === "auth" ? "info" : ""}>
                {a.category}
              </Badge>
              <span style={{ fontWeight: 550, fontSize: 13.5 }}>{a.action}</span>
            </div>
            <div className="feed-time">{fmtDate(a.created_at)}</div>
          </div>
        ))}
      </div>
    </Layout>
  );
}
