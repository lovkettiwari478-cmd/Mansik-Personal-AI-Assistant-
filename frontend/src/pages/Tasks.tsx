/* Tasks page — full CRUD with priorities, due dates, recurrence. */

import { useCallback, useEffect, useState } from "react";
import { fmtDate, taskApi } from "../api";
import { useToast } from "../state";
import { Badge, EmptyState, Field, Loading, Modal } from "../components/ui";
import Layout from "../components/Layout";

const STATUSES = ["todo", "in_progress", "done", "cancelled"];

export default function TasksPage() {
  const { push } = useToast();
  const [tasks, setTasks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [modal, setModal] = useState(false);
  const [form, setForm] = useState({
    title: "", notes: "", priority: "medium", due_at: "", recurrence: "none",
  });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await taskApi.list(filter === "all" ? undefined : filter);
      setTasks(r.tasks);
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [filter, push]);

  useEffect(() => { load(); }, [load]);

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
      load();
    } catch (e: any) { push(e.message, "error"); }
  };

  return (
    <Layout title="Tasks" subtitle="Priorities, deadlines, recurrence — managed by you or MANISK">
      <div className="row wrap mb-14">
        <button className="btn small" onClick={() => setModal(true)}>+ New task</button>
        {["all", ...STATUSES].map((s) => (
          <button
            key={s} className={`btn small ${filter === s ? "" : "secondary"}`}
            onClick={() => setFilter(s)}
          >
            {s.replace("_", " ")}
          </button>
        ))}
      </div>

      {loading ? <Loading /> : tasks.length === 0 ? (
        <EmptyState icon="✓" title="No tasks here" hint="Create one, or ask MANISK: “create task … due tomorrow 5pm”" />
      ) : (
        tasks.map((t) => {
          const overdue = t.due_at && new Date(t.due_at) < new Date() && t.status !== "done";
          return (
            <div key={t.id} className="list-item">
              <button
                className="btn ghost small"
                style={{ padding: "2px 6px" }}
                aria-label={t.status === "done" ? "Reopen" : "Mark done"}
                onClick={() => setStatus(t.id, t.status === "done" ? "todo" : "done")}
              >
                {t.status === "done" ? "↺" : "○"}
              </button>
              <div className="grow">
                <div style={{ fontWeight: 600, textDecoration: t.status === "done" ? "line-through" : "none" }}>
                  {t.title}
                </div>
                {t.notes && <div className="small muted">{t.notes}</div>}
                <div className="small faint mt-8">
                  {t.due_at ? `due ${fmtDate(t.due_at)}` : "no due date"}
                  {t.recurrence !== "none" && ` · repeats ${t.recurrence}`}
                </div>
              </div>
              <div className="row">
                <Badge kind={t.priority === "urgent" ? "danger" : t.priority === "high" ? "warning" : ""}>
                  {t.priority}
                </Badge>
                {overdue && <Badge kind="danger">overdue</Badge>}
                <select
                  className="select" style={{ width: "auto", padding: "5px 8px", fontSize: 12 }}
                  value={t.status} onChange={(e) => setStatus(t.id, e.target.value)}
                  aria-label="Status"
                >
                  {STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
                </select>
                <button className="btn ghost small" onClick={() => remove(t.id)} aria-label="Delete">🗑</button>
              </div>
            </div>
          );
        })
      )}

      {modal && (
        <Modal title="New task" onClose={() => setModal(false)}>
          <Field label="Title">
            <input className="input" value={form.title} maxLength={300}
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
    </Layout>
  );
}
