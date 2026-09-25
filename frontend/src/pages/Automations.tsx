/* Automations v2 — Automation Center: schedules, permissions,
 * next/last execution, run history, honest authorization state. */

import { useCallback, useEffect, useState } from "react";
import { api, automationApi, fmtDate, securityApi } from "../api";
import { useToast } from "../state";
import { Badge, EmptyState, Field, Loading, Modal } from "../components/ui";
import Layout from "../components/Layout";

export default function AutomationsPage() {
  const { push } = useToast();
  const [automations, setAutomations] = useState<any[]>([]);
  const [tools, setTools] = useState<any[]>([]);
  const [permissions, setPermissions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(false);
  const [runsFor, setRunsFor] = useState<string | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "", trigger_type: "interval",
    every_seconds: 3600, at_hhmm: "09:00",
    action_tool: "notify.user",
    action_params_json: '{"title": "Hello", "body": "From your automation"}',
  });

  const load = useCallback(async () => {
    try {
      const [a, t, p] = await Promise.all([automationApi.list(), api("/api/tools"), securityApi.permissions()]);
      setAutomations(a.automations);
      setTools(t.tools);
      setPermissions(p.permissions);
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [push]);

  useEffect(() => { load(); }, [load]);

  const openRuns = async (id: string) => {
    setRunsFor(id);
    try {
      const r = await automationApi.runs(id);
      setRuns(r.runs);
    } catch (e: any) { push(e.message, "error"); }
  };

  const create = async () => {
    setBusy(true);
    try {
      const params = JSON.parse(form.action_params_json || "{}");
      await automationApi.create({
        name: form.name,
        trigger_type: form.trigger_type,
        trigger_config: form.trigger_type === "interval"
          ? { every_seconds: Number(form.every_seconds) }
          : { at_hhmm: form.at_hhmm },
        action_tool: form.action_tool,
        action_params: params,
        enabled: false,
      });
      push("Automation created (disabled). Grant its permission in Security, then enable.", "success");
      setModal(false);
      setForm({ ...form, name: "" });
      load();
    } catch (e: any) {
      push(e.message || "Invalid parameters (JSON?)", "error");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (a: any) => {
    try {
      await automationApi.update(a.id, { enabled: !a.enabled });
      push(a.enabled ? "Automation disabled" : "Automation enabled — runs on schedule (audited)", "success");
      load();
    } catch (e: any) { push(e.message, "error"); }
  };

  const remove = async (id: string) => {
    if (!confirm("Delete this automation?")) return;
    try { await automationApi.remove(id); load(); } catch (e: any) { push(e.message, "error"); }
  };

  const grantedScopes = new Set(permissions.filter((p: any) => p.granted).map((p: any) => p.scope));
  const active = automations.filter((a) => a.enabled);
  const inactive = automations.filter((a) => !a.enabled);

  const AutomationRow = ({ a }: { a: any }) => {
    const tool = tools.find((t: any) => t.id === a.action_tool);
    const hasGrant = !tool?.scope || grantedScopes.has(tool.scope);
    return (
      <div className="list-item">
        <div className={`prio ${a.enabled ? "medium" : "low"}`} />
        <div className="grow">
          <div className="row wrap">
            <strong>{a.name}</strong>
            <Badge kind={a.enabled ? "success" : ""}>{a.enabled ? "active" : "disabled"}</Badge>
            {!hasGrant && <Badge kind="warning">permission missing</Badge>}
          </div>
          <div className="small muted mt-8">
            {a.trigger_type === "interval"
              ? `every ${Math.round(a.trigger_config.every_seconds / 60)} min`
              : `daily at ${a.trigger_config.at_hhmm}`}
            {" → "}
            <span className="mono">{a.action_tool}</span>
          </div>
          <div className="small faint">
            {a.last_run_at ? `last run ${fmtDate(a.last_run_at)}` : "never run"}
            {a.next_run_at && a.enabled && ` · next ${fmtDate(a.next_run_at)}`}
          </div>
          {/* what MANISK is authorized to do */}
          <div className="small faint mt-8">
            authorized via <span className="mono">{tool?.scope || "—"}</span>{" "}
            ({hasGrant ? "standing grant ✓" : "not granted — enable blocked"})
          </div>
        </div>
        <div className="row">
          <button className={`btn small ${a.enabled ? "secondary" : ""}`} onClick={() => toggle(a)}>
            {a.enabled ? "Disable" : "Enable"}
          </button>
          <button className="btn secondary small" onClick={() => openRuns(a.id)}>Logs</button>
          <button className="btn ghost small" onClick={() => remove(a.id)} aria-label="Delete">🗑</button>
        </div>
      </div>
    );
  };

  return (
    <Layout title="Automations" subtitle="Scheduled tool execution — only with your explicit standing permission">
      <div className="row wrap mb-14">
        <button className="btn small" onClick={() => setModal(true)}>＋ New automation</button>
        <span className="small faint">
          {active.length} active · {inactive.length} disabled — enabling requires a standing grant (Security).
        </span>
      </div>

      {loading ? <Loading /> : automations.length === 0 ? (
        <EmptyState icon="⚡" title="No automations"
          hint="e.g. hourly reminders, or a daily 09:0 0 task digest (notify tool)" />
      ) : (
        <>
          {active.length > 0 && <div className="nav-section" style={{ paddingLeft: 0 }}>Active</div>}
          {active.map((a) => <AutomationRow key={a.id} a={a} />)}
          {inactive.length > 0 && <div className="nav-section" style={{ paddingLeft: 0 }}>Disabled</div>}
          {inactive.map((a) => <AutomationRow key={a.id} a={a} />)}
        </>
      )}

      {modal && (
        <Modal title="New automation" onClose={() => setModal(false)} wide>
          <Field label="Name">
            <input className="input" value={form.name} maxLength={200} autoFocus
                   onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Field label="Trigger">
              <select className="select" value={form.trigger_type}
                      onChange={(e) => setForm({ ...form, trigger_type: e.target.value })}>
                <option value="interval">Interval (repeating)</option>
                <option value="daily_at">Daily at time</option>
              </select>
            </Field>
            {form.trigger_type === "interval" ? (
              <Field label="Every N seconds (min 300)">
                <input className="input" type="number" min={300} step={60} value={form.every_seconds}
                       onChange={(e) => setForm({ ...form, every_seconds: Number(e.target.value) })} />
              </Field>
            ) : (
              <Field label="At (HH:MM)">
                <input className="input" type="time" value={form.at_hhmm}
                       onChange={(e) => setForm({ ...form, at_hhmm: e.target.value })} />
              </Field>
            )}
          </div>
          <Field label="Action tool">
            <select className="select" value={form.action_tool}
                    onChange={(e) => setForm({ ...form, action_tool: e.target.value })}>
              {tools.filter((t: any) => t.scope).map((t: any) => (
                <option key={t.id} value={t.id} disabled={!t.available}>
                  {t.id}{t.available ? "" : " (unavailable)"}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Tool parameters (JSON)">
            <textarea className="textarea mono" value={form.action_params_json}
                      onChange={(e) => setForm({ ...form, action_params_json: e.target.value })} />
          </Field>
          <div className="small faint mb-14">
            Created disabled. Grant <span className="mono">
              {tools.find((t) => t.id === form.action_tool)?.scope}
            </span> in Security before enabling.
          </div>
          <button className="btn" style={{ width: "100%" }} disabled={busy || !form.name.trim()} onClick={create}>
            Create automation
          </button>
        </Modal>
      )}

      {runsFor && (
        <Modal title="Execution history" onClose={() => setRunsFor(null)} wide>
          {runs.length === 0 ? (
            <EmptyState icon="≡" title="No runs yet" />
          ) : runs.map((r) => (
            <div key={r.id} className="list-item">
              <div className="grow">
                <div className="row">
                  <Badge kind={r.status === "success" ? "success" : r.status === "skipped" ? "warning" : "danger"}>
                    {r.status}
                  </Badge>
                  <span className="small faint">{fmtDate(r.started_at)} · attempt {r.attempt}</span>
                </div>
                {r.error && <div className="small" style={{ color: "var(--danger)" }}>{r.error}</div>}
                {r.result && Object.keys(r.result).length > 0 && (
                  <div className="confirm-params">{JSON.stringify(r.result, null, 2).slice(0, 500)}</div>
                )}
              </div>
            </div>
          ))}
        </Modal>
      )}
    </Layout>
  );
}
