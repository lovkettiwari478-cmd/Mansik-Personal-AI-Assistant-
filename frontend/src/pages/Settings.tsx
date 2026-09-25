/* Settings v2 — personalization: assistant name, response style,
 * timezone, memory; password; account info. */

import { useEffect, useState } from "react";
import { authApi, settingsApi } from "../api";
import { useAuth, useToast } from "../state";
import { Field, Loading, Toggle } from "../components/ui";
import Layout from "../components/Layout";

const TIMEZONES = [
  "UTC", "Asia/Kolkata", "Asia/Tokyo", "Asia/Singapore", "Asia/Dubai",
  "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Moscow",
  "America/New_York", "America/Chicago", "America/Los_Angeles", "America/Sao_Paulo",
  "Australia/Sydney", "Africa/Cairo", "Africa/Lagos",
];

const STYLES = [
  { key: "concise", label: "Concise", hint: "Short, direct answers" },
  { key: "balanced", label: "Balanced", hint: "Clear and complete" },
  { key: "detailed", label: "Detailed", hint: "Thorough and structured" },
];

export default function SettingsPage() {
  const { user } = useAuth();
  const { push } = useToast();
  const [settings, setSettings] = useState<any>(null);
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });

  useEffect(() => {
    (async () => {
      const s = await settingsApi.get();
      setSettings(s);
      setDisplayName(s.display_name);
    })();
  }, []);

  if (!settings) return <Layout title="Settings"><Loading /></Layout>;

  const saveProfile = async () => {
    setBusy(true);
    try {
      await settingsApi.patch({
        display_name: displayName,
        timezone: settings.timezone,
        assistant_name: settings.assistant_name,
        response_style: settings.response_style,
        memory_enabled: settings.memory_enabled,
      });
      push("Settings saved", "success");
    } catch (e: any) { push(e.message, "error"); }
    finally { setBusy(false); }
  };

  const changePassword = async () => {
    if (pw.next !== pw.confirm) { push("New passwords don't match", "error"); return; }
    setBusy(true);
    try {
      const r = await authApi.changePassword(pw.current, pw.next);
      push(`Password changed — ${r.sessions_revoked} other session(s) signed out`, "success");
      setPw({ current: "", next: "", confirm: "" });
    } catch (e: any) { push(e.message, "error"); }
    finally { setBusy(false); }
  };

  return (
    <Layout title="Settings" subtitle="Personalization · preferences · account">
      {/* personalization */}
      <div className="card">
        <div className="card-title">Personalization</div>
        <div className="card-sub">Make MANISK yours — the assistant's name and how it responds.</div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Field label="Assistant name">
            <input
              className="input" value={settings.assistant_name} maxLength={40}
              onChange={(e) => setSettings({ ...settings, assistant_name: e.target.value })}
              placeholder="MANISK"
            />
          </Field>
          <Field label="Your name">
            <input className="input" value={displayName} maxLength={120}
                   onChange={(e) => setDisplayName(e.target.value)} />
          </Field>
        </div>
        <Field label="Response style">
          <div className="seg" style={{ width: "100%" }}>
            {STYLES.map((s) => (
              <button key={s.key} className={`seg-btn ${settings.response_style === s.key ? "active" : ""}`}
                      style={{ flex: 1 }}
                      onClick={() => setSettings({ ...settings, response_style: s.key })}
                      title={s.hint}>
                {s.label}
              </button>
            ))}
          </div>
          <div className="small faint" style={{ marginTop: 6 }}>
            {STYLES.find((s) => s.key === settings.response_style)?.hint}
          </div>
        </Field>
        <Field label="Timezone">
          <select
            className="select" value={settings.timezone}
            onChange={(e) => setSettings({ ...settings, timezone: e.target.value })}
          >
            {TIMEZONES.map((tz) => <option key={tz}>{tz}</option>)}
          </select>
        </Field>
        <Toggle
          on={settings.memory_enabled}
          onChange={(v) => setSettings({ ...settings, memory_enabled: v })}
          label="Long-term memory"
          description="MANISK stores and retrieves facts you share (manage in Memory)."
        />
        <button className="btn mt-14" disabled={busy} onClick={saveProfile}>Save settings</button>
      </div>

      {/* password */}
      <div className="card mt-14">
        <div className="card-title">Change password</div>
        <div className="card-sub">Changing your password signs out all other devices.</div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
          <div className="field">
            <label>Current</label>
            <input className="input" type="password" value={pw.current} autoComplete="current-password"
                   onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          </div>
          <div className="field">
            <label>New (10+ chars)</label>
            <input className="input" type="password" value={pw.next} autoComplete="new-password"
                   onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          </div>
          <div className="field">
            <label>Confirm new</label>
            <input className="input" type="password" value={pw.confirm} autoComplete="new-password"
                   onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
          </div>
        </div>
        <button className="btn" disabled={busy || !pw.current || !pw.next} onClick={changePassword}>
          Change password
        </button>
      </div>

      {/* account */}
      <div className="card mt-14">
        <div className="card-title">Account</div>
        <div className="small muted">
          <div className="row between mb-8">
            <span className="faint">Email</span><span>{user?.email}</span>
          </div>
          <div className="row between mb-8">
            <span className="faint">Member since</span>
            <span>{new Date(user?.created_at || "").toLocaleDateString()}</span>
          </div>
        </div>
        <div className="small faint mt-14">
          MANISK · Personal AI Operating System · v0.2.0<br />
          Your data (conversations, memories, tasks, files) is isolated to your account.
          Secrets and API keys are kept server-side only.
        </div>
      </div>
    </Layout>
  );
}
