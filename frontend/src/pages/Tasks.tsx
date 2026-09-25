/* Tasks v2 — Today / Upcoming / Completed / All, priority accents,
 * quick complete, details. Real backend data only. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { fmtDate, taskApi } from "../api";
import { useToast } from "../state";
import { Badge, EmptyState, Field, Loading, Modal } from "../components/ui";
import Layout from "../components/Layout";

const STATUSES = ["todo", "in_progress", "done", "cancelled"];
type View = "today" | "upcoming" | "completed" | "all";

export default function TasksPage() {
  const { push } = useToast();
  const [tasks, setTasks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<View>("today");
  const [modal, setModal] = useState(false);
  const [detail, setDetail] = useState<any | null>(null);
  const [form, setForm] = useState({
    title: "", notes: "", priority: "medium", due_at: "", recurrence: "none",
  });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await taskApi.list();
      setTasks(r.tasks);
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [push]);

  useEffect(() => { load(); }, [load]);

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  const filtered = useMemo(() => {
    const open = tasks.filter((t) => t.status === "todo" || t.status === "in_progress");
    switch (view) {
      case "today":
        return open.filter((t) =>
          t.due_at && new Date(t.due_at) < new Date(startOfToday.getTime() + 86400000));
      case "upcoming":
        return open.filter((t) =>
          !t.due_at || new Date(t.due_at) >= new Date(startOfToday.getTime() + 86400000));
      case "completed":
        return tasks.filter((t) => t.status === "done" || t.status === "cancelled");
      default:
        return tasks;
    }
  }, [tasks, view]);

  const counts = useMemo(() => ({
    today: tasks.filter((t) => (t.status === "todo" || t.status === "in_progress") &&
      t.due_at && new Date(t.due_at) < new Date(startOfToday.getTime() + 86400000)).length,
    upcoming: tasks.filter((t) => (t.status === "todo" || t.status === "in_progress") &&
      (!t.due_at || new Date(t.due_at) >= new Date(startOfToday.getTime() + 86400000))).length,
    completed: tasks.filter((t) => t.status === "done" || t.status === "cancelled").length,
    all: tasks.length,
  }), [tasks]);

  const create = async () => {
    if (!form.title.trim()) return;
    setBusy(true);
    try {
      await taskApi.create({
        ...form,
        due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
      });
      push("Task created", "success");
      setModal(false);
      setForm({ title: "", notes: "", priority: "medium", due_at: "", recurrence: "none" });
      load();
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (id: string, status: string) => {
    try {
      await taskApi.update(id, { status });
      load();
    } catch (e: any) { push(e.message, "error"); }
  };

  const remove = async (id: string) => {
    if (!confirm("Delete this task?")) return;
    try {
      await taskApi.remove(id);
      push("Task deleted", "success");
      setDetail(null);
      load();
    } catch (e: any) { push(e.message, "error"); }
  };

  const views: { key: View; label: string }[] = [
    { key: "today", label: `Today · ${counts.today}` },
    { key: "upcoming", label: `Upcoming · ${counts.upcoming}` },
    { key: "completed", label: `Completed · ${counts.completed}` },
    { key: "all", label: `All · ${counts.all}` },
  ];

  return (
    <Layout title="Tasks" subtitle="Priorities · deadlines · recurrence — yours or MANISK's">
      <div className="row wrap mb-14">
        <button className="btn small" onClick={() => setModal(true)}>＋ New task</button>
        <div className="seg">
          {views.map((v) => (
            <button key={v.key} className={`seg-btn ${view === v.key ? "active" : ""}`}
                    onClick={() => setView(v.key)}>
              {v.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? <Loading /> : filtered.length === 0 ? (
        <EmptyState
          icon="✓"
          title={view === "today" ? "Nothing due today" : view === "upcoming" ? "No upcoming tasks" : view === "completed" ? "Nothing completed yet" : "No tasks"}
          hint="Ask MANISK: “create task … due tomorrow 5pm”"
        />
      ) : filtered.map((t) => {
        const overdue = t.due_at && new Date(t.due_at) < now && t.status !== "done";
        return (
          <div key={t.id} className="list-item clickable" onClick={() => setDetail(t)}>
            <div className={`prio ${t.priority}`} />
            <button
              className="btn ghost small" style={{ padding: "2px 6px" }}
              aria-label={t.status === "done" ? "Reopen" : "Mark done"}
              onClick={(e) => { e.stopPropagation(); setStatus(t.id, t.status === "done" ? "todo" : "done"); }}
            >
              {t.status === "done" ? "↺" : "○"}
            </button>
            <div className="grow">
              <div style={{ fontWeight: 600, textDecoration: t.status === "done" ? "line-through" : "none" }}>
                {t.title}
              </div>
              <div className="small faint">
                {t.due_at ? `due ${fmtDate(t.due_at)}` : "no due date"}
                {t.recurrence !== "none" && ` · ↻ ${t.recurrence}`}
                {t.status === "in_progress" && " · in progress"}
              </div>
            </div>
            {overdue && <Badge kind="danger">overdue</Badge>}
            <Badge kind={t.priority === "urgent" ? "danger" : t.priority === "high" ? "warning" : ""}>
              {t.priority}
            </Badge>
          </div>
        );
      })}

      {modal && (
        <Modal title="New task" onClose={() => setModal(false)}>
          <Field label="Title">
            <input className="input" value={form.title} maxLength={300} autoFocus
                   onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Notes (optional)">
            <textarea className="textarea" value={form.notes}
                      onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </Field>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Field label="Priority">
              <select className="select" value={form.priority}
                      onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {["low", "medium", "high", "urgent"].map((p) => <option key={p}>{p}</option>)}
              </select>
            </Field>
            <Field label="Recurrence">
              <select className="select" value={form.recurrence}
                      onChange={(e) => setForm({ ...form, recurrence: e.target.value })}>
                {["none", "daily", "weekly", "monthly"].map((p) => <option key={p}>{p}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Due date & time (optional)">
            <input className="input" type="datetime-local" value={form.due_at}
                   onChange={(e) => setForm({ ...form, due_at: e.target.value })} />
          </Field>
          <button className="btn" style={{ width: "100%" }} disabled={busy || !form.title.trim()} onClick={create}>
            Create task
          </button>
        </Modal>
      )}

      {detail && (
        <Modal title={detail.title} onClose={() => setDetail(null)}>
          <div className="row wrap mb-14">
            <Badge kind={detail.priority === "urgent" ? "danger" : detail.priority === "high" ? "warning" : ""}>
              {detail.priority}
            </Badge>
            <Badge kind={detail.status === "done" ? "success" : "info"}>{detail.status.replace("_", " ")}</Badge>
            {detail.recurrence !== "none" && <Badge>↻ {detail.recurrence}</Badge>}
          </div>
          {detail.notes && <p className="muted small" style={{ whiteSpace: "pre-wrap" }}>{detail.notes}</p>}
          <div className="small faint mb-14">
            {detail.due_at ? `Due ${fmtDate(detail.due_at)}` : "No due date"}
            <br />Created {fmtDate(detail.created_at)}
          </div>
          <div className="row wrap">
            {detail.status !== "done" && (
              <button className="btn small" onClick={() => { setStatus(detail.id, "done"); setDetail(null); }}>
                ✓ Mark done
              </button>
            )}
            <select
              className="select" style={{ width: "auto", padding: "6px 30px 6px 10px", fontSize: 12.5 }}
              value={detail.status}
              onChange={(e) => { setStatus(detail.id, e.target.value); setDetail(null); }}
              aria-label="Set status"
            >
              {STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
            </select>
            <button className="btn danger small" onClick={() => remove(detail.id)}>🗑 Delete</button>
          </div>
        </Modal>
      )}
    </Layout>
  );
}
