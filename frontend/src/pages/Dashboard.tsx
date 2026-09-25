/* Dashboard — overview of the whole OS. */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  calendarApi, fmtDate, memoryApi, securityApi, statusApi, taskApi,
} from "../api";
import { useAuth, useStatus } from "../state";
import { Badge, EmptyState, Loading } from "../components/ui";
import Layout from "../components/Layout";

export default function DashboardPage() {
  const { user } = useAuth();
  const { aiConfigured, aiModel } = useStatus();
  const [tasks, setTasks] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [memories, setMemories] = useState<any[]>([]);
  const [emergency, setEmergency] = useState(false);
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [t, e, m, s, h] = await Promise.all([
          taskApi.list(), calendarApi.list(7), memoryApi.list(),
          securityApi.emergencyStopStatus(), statusApi.health(),
        ]);
        setTasks(t.tasks.filter((x: any) => x.status === "todo" || x.status === "in_progress"));
        setEvents(e.events);
        setMemories(m.memories);
        setEmergency(s.active);
        setHealth(h);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <Layout title="Dashboard"><Loading /></Layout>;

  const overdue = tasks.filter((t) => t.due_at && new Date(t.due_at) < new Date());

  return (
    <Layout title="Dashboard" subtitle={`Welcome back, ${user?.display_name}`}>
      {emergency && (
        <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 14 }} role="alert">
          <div className="row">
            <span style={{ fontSize: 22 }} aria-hidden>🛑</span>
            <div className="grow">
              <strong>Emergency stop is active.</strong>
              <div className="small muted">
                All tools and automations are halted. Release it from the Security page.
              </div>
            </div>
            <Link to="/security" className="btn small danger">Security</Link>
          </div>
        </div>
      )}

      <div className="grid cols-3">
        <div className="stat">
          <div className="stat-label">Open tasks</div>
          <div className="stat-value">{tasks.length}</div>
          {overdue.length > 0 && <Badge kind="danger">{overdue.length} overdue</Badge>}
        </div>
        <div className="stat">
          <div className="stat-label">Events · next 7 days</div>
          <div className="stat-value">{events.length}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Memories</div>
          <div className="stat-value">{memories.length}</div>
        </div>
      </div>

      <div className="grid cols-2 mt-14">
        <div className="card">
          <div className="row between mb-14">
            <div className="card-title">Up next</div>
            <Link to="/tasks" className="small">All tasks →</Link>
          </div>
          {tasks.length === 0 && <EmptyState icon="✓" title="Nothing pending" hint="Ask MANISK to create tasks in chat." />}
          {tasks.slice(0, 5).map((t) => (
            <div key={t.id} className="list-item">
              <div className="grow">
                <div style={{ fontWeight: 600 }}>{t.title}</div>
                <div className="small faint">
                  {t.due_at ? `due ${fmtDate(t.due_at)}` : "no due date"} · {t.priority}
                </div>
              </div>
              <Badge kind={t.status === "in_progress" ? "info" : ""}>{t.status}</Badge>
            </div>
          ))}
        </div>

        <div className="card">
          <div className="row between mb-14">
            <div className="card-title">Next events</div>
            <Link to="/calendar" className="small">Calendar →</Link>
          </div>
          {events.length === 0 && <EmptyState icon="📅" title="No events this week" />}
          {events.slice(0, 5).map((e) => (
            <div key={e.id} className="list-item">
              <div className="grow">
                <div style={{ fontWeight: 600 }}>{e.title}</div>
                <div className="small faint">{fmtDate(e.starts_at)}{e.location ? ` · ${e.location}` : ""}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card mt-14">
        <div className="card-title">System status</div>
        <div className="card-sub">Honest, live status — no fake indicators.</div>
        <div className="grid cols-2">
          <div className="row between" style={{ padding: "8px 0" }}>
            <span className="muted small">Backend</span>
            <Badge kind={health?.status === "ok" ? "success" : "danger"}>{health?.status || "unknown"}</Badge>
          </div>
          <div className="row between" style={{ padding: "8px 0" }}>
            <span className="muted small">Database</span>
            <Badge kind={health?.database ? "success" : "danger"}>{health?.database ? "connected" : "down"}</Badge>
          </div>
          <div className="row between" style={{ padding: "8px 0" }}>
            <span className="muted small">AI provider</span>
            <Badge kind={aiConfigured ? "success" : "warning"}>
              {aiConfigured ? (aiModel || "configured") : "not configured (Local Mode)"}
            </Badge>
          </div>
          <div className="row between" style={{ padding: "8px 0" }}>
            <span className="muted small">Emergency stop</span>
            <Badge kind={emergency ? "danger" : "success"}>{emergency ? "ACTIVE" : "off"}</Badge>
          </div>
        </div>
        <div className="small faint mt-8">
          To enable full AI conversation, the operator sets MANISK_AI_BASE_URL + MANISK_AI_MODEL
          (any OpenAI-compatible API: NVIDIA NIM/Nemotron, OpenAI, Groq, Together, Ollama…).
          See Integrations.
        </div>
      </div>
    </Layout>
  );
}
