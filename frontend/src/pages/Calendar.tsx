/* Calendar page — events grouped by day, with reminders. */

import { useCallback, useEffect, useState } from "react";
import { calendarApi } from "../api";
import { useToast } from "../state";
import { Badge, EmptyState, Field, Loading, Modal } from "../components/ui";
import Layout from "../components/Layout";

function dayKey(iso: string) {
  return new Date(iso).toDateString();
}

export default function CalendarPage() {
  const { push } = useToast();
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(false);
  const [form, setForm] = useState({
    title: "", description: "", location: "",
    starts_at: "", ends_at: "", reminder_minutes: "",
  });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await calendarApi.list(60);
      setEvents(r.events);
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [push]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    setBusy(true);
    try {
      await calendarApi.create({
        title: form.title,
        description: form.description,
        location: form.location,
        starts_at: new Date(form.starts_at).toISOString(),
        ends_at: new Date(form.ends_at || form.starts_at).toISOString(),
        reminder_minutes: form.reminder_minutes ? Number(form.reminder_minutes) : null,
      });
      push("Event created", "success");
      setModal(false);
      setForm({ title: "", description: "", location: "", starts_at: "", ends_at: "", reminder_minutes: "" });
      load();
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!confirm("Delete this event?")) return;
    try {
      await calendarApi.remove(id);
      load();
    } catch (e: any) { push(e.message, "error"); }
  };

  const byDay: Record<string, any[]> = {};
  events.forEach((e) => {
    const k = dayKey(e.starts_at);
    (byDay[k] = byDay[k] || []).push(e);
  });
  const days = Object.keys(byDay).sort();

  return (
    <Layout title="Calendar" subtitle="Events, reminders and conflict awareness">
      <div className="row mb-14">
        <button className="btn small" onClick={() => setModal(true)}>+ New event</button>
        <span className="small faint">Next 60 days</span>
      </div>

      {loading ? <Loading /> : events.length === 0 ? (
        <EmptyState icon="📅" title="No upcoming events" hint="Ask MANISK: “schedule Dentist next monday 3pm”" />
      ) : (
        days.map((day) => (
          <div key={day} className="mb-14">
            <div className="row between mb-8">
              <strong>{day}</strong>
              <span className="small faint">{byDay[day].length} event{byDay[day].length > 1 ? "s" : ""}</span>
            </div>
            {byDay[day].map((e) => (
              <div key={e.id} className="list-item">
                <div className="grow">
                  <div style={{ fontWeight: 600 }}>{e.title}</div>
                  <div className="small muted">
                    {new Date(e.starts_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                    {" – "}
                    {new Date(e.ends_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                    {e.location && ` · ${e.location}`}
                  </div>
                  {e.reminder_minutes != null && (
                    <div className="small faint">reminder {e.reminder_minutes} min before</div>
                  )}
                </div>
                {e.recurrence !== "none" && <Badge kind="info">{e.recurrence}</Badge>}
                <button className="btn ghost small" onClick={() => remove(e.id)} aria-label="Delete">🗑</button>
              </div>
            ))}
          </div>
        ))
      )}

      {modal && (
        <Modal title="New event" onClose={() => setModal(false)}>
          <Field label="Title">
            <input className="input" value={form.title} maxLength={300}
                   onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Location (optional)">
            <input className="input" value={form.location}
                   onChange={(e) => setForm({ ...form, location: e.target.value })} />
          </Field>
          <Field label="Starts">
            <input className="input" type="datetime-local" value={form.starts_at}
                   onChange={(e) => setForm({ ...form, starts_at: e.target.value })} />
          </Field>
          <Field label="Ends">
            <input className="input" type="datetime-local" value={form.ends_at}
                   onChange={(e) => setForm({ ...form, ends_at: e.target.value })} />
          </Field>
          <Field label="Reminder (minutes before, optional)">
            <input className="input" type="number" min={0} value={form.reminder_minutes}
                   onChange={(e) => setForm({ ...form, reminder_minutes: e.target.value })} />
          </Field>
          <button className="btn" style={{ width: "100%" }} disabled={busy || !form.title || !form.starts_at || !form.ends_at}
                  onClick={create}>
            Create event
          </button>
        </Modal>
      )}
    </Layout>
  );
}
