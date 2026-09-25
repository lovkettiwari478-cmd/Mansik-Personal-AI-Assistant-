/* Calendar v2 — day-grouped timeline, today highlighting,
 * reminders, recurrence badges, mobile-friendly. */

import { useCallback, useEffect, useState } from "react";
import { calendarApi } from "../api";
import { useToast } from "../state";
import { Badge, EmptyState, Field, Loading, Modal } from "../components/ui";
import Layout from "../components/Layout";

function dayInfo(iso: string) {
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return {
    key: d.toDateString(),
    label: sameDay ? "Today" : d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }),
    dom: d.getDate(),
    dow: d.toLocaleDateString(undefined, { weekday: "short" }),
    sameDay,
    past: d < today && !sameDay,
  };
}

export default function CalendarPage() {
  const { push } = useToast();
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(false);
  const [form, setForm] = useState({
    title: "", description: "", location: "",
    starts_at: "", ends_at: "", reminder_minutes: "", recurrence: "none",
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
        recurrence: form.recurrence,
      });
      push("Event created", "success");
      setModal(false);
      setForm({ title: "", description: "", location: "", starts_at: "", ends_at: "", reminder_minutes: "", recurrence: "none" });
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
      push("Event deleted", "success");
      load();
    } catch (e: any) { push(e.message, "error"); }
  };

  const byDay: Record<string, { info: any; events: any[] }> = {};
  events.forEach((e) => {
    const info = dayInfo(e.starts_at);
    (byDay[info.key] = byDay[info.key] || { info, events: [] }).events.push(e);
  });
  const days = Object.values(byDay).sort((a, b) =>
    new Date(a.events[0].starts_at).getTime() - new Date(b.events[0].starts_at).getTime());

  return (
    <Layout title="Calendar" subtitle="Events, reminders and recurrence — next 60 days">
      <div className="row wrap mb-14">
        <button className="btn small" onClick={() => setModal(true)}>＋ New event</button>
        <span className="small faint">
          {events.length} upcoming · or ask MANISK: “schedule dentist next Monday at 3pm”
        </span>
      </div>

      {loading ? <Loading /> : events.length === 0 ? (
        <EmptyState icon="▤" title="No upcoming events"
          hint='Try: "schedule a team sync tomorrow 10am with a 15 min reminder"' />
      ) : (
        days.map(({ info, events: dayEvents }) => (
          <div key={info.key} className="day-group">
            <div className="day-head">
              <div className={`day-chip ${info.sameDay ? "today" : ""}`}>
                <div className="day-dom">{info.dom}</div>
                <div className="day-dow">{info.dow}</div>
              </div>
              <div className="grow">
                <strong style={{ opacity: info.past ? 0.55 : 1 }}>{info.label}</strong>
                <span className="small faint" style={{ marginLeft: 10 }}>
                  {dayEvents.length} event{dayEvents.length > 1 ? "s" : ""}
                </span>
              </div>
            </div>
            {dayEvents.map((e) => {
              const conflicts = dayEvents.filter((o) => o.id !== e.id &&
                new Date(o.starts_at) < new Date(e.ends_at) &&
                new Date(o.starts_at) >= new Date(e.starts_at));
              return (
                <div key={e.id} className="list-item">
                  <div className={`prio ${conflicts.length ? "high" : "medium"}`} />
                  <div className="grow">
                    <div className="row wrap">
                      <span style={{ fontWeight: 600 }}>{e.title}</span>
                      {e.recurrence && e.recurrence !== "none" && <Badge kind="info">↻ {e.recurrence}</Badge>}
                      {conflicts.length > 0 && <Badge kind="warning">overlaps {conflicts.length}</Badge>}
                    </div>
                    <div className="small muted mt-8">
                      {new Date(e.starts_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                      {" – "}
                      {new Date(e.ends_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                      {e.location && ` · ${e.location}`}
                    </div>
                    {e.description && <div className="small faint">{e.description}</div>}
                    {e.reminder_minutes != null && (
                      <div className="small faint">reminder {e.reminder_minutes} min before</div>
                    )}
                  </div>
                  <button className="btn ghost small" onClick={() => remove(e.id)} aria-label="Delete">🗑</button>
                </div>
              );
            })}
          </div>
        ))
      )}

      {modal && (
        <Modal title="New event" onClose={() => setModal(false)}>
          <Field label="Title">
            <input className="input" value={form.title} maxLength={300} autoFocus
                   onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Field label="Starts">
              <input className="input" type="datetime-local" value={form.starts_at}
                     onChange={(e) => setForm({ ...form, starts_at: e.target.value })} />
            </Field>
            <Field label="Ends">
              <input className="input" type="datetime-local" value={form.ends_at}
                     onChange={(e) => setForm({ ...form, ends_at: e.target.value })} />
            </Field>
          </div>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Field label="Location (optional)">
              <input className="input" value={form.location}
                     onChange={(e) => setForm({ ...form, location: e.target.value })} />
            </Field>
            <Field label="Reminder (minutes before)">
              <input className="input" type="number" min={0} placeholder="none"
                     value={form.reminder_minutes}
                     onChange={(e) => setForm({ ...form, reminder_minutes: e.target.value })} />
            </Field>
          </div>
          <Field label="Recurrence">
            <select className="select" value={form.recurrence}
                    onChange={(e) => setForm({ ...form, recurrence: e.target.value })}>
              <option value="none">None</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </Field>
          <Field label="Description (optional)">
            <textarea className="textarea" value={form.description} maxLength={2000}
                      onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <button className="btn" style={{ width: "100%" }}
                  disabled={busy || !form.title || !form.starts_at || !form.ends_at} onClick={create}>
            Create event
          </button>
        </Modal>
      )}
    </Layout>
  );
}
