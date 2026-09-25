/* Settings page — profile, timezone, theme, password change, data controls. */

import { useEffect, useState } from "react";
import { authApi, settingsApi } from "../api";
import { useAuth, useToast } from "../state";
import { Field, Loading } from "../components/ui";
import Layout from "../components/Layout";

const TIMEZONES = [
  "UTC", "Asia/Kolkata", "Asia/Tokyo", "Asia/Singapore", "Asia/Dubai",
  "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Moscow",
  "America/New_York", "America/Chicago", "America/Los_Angeles", "America/Sao_Paulo",
  "Australia/Sydney", "Africa/Cairo", "Africa/Lagos",
];

export default function SettingsPage() {
  const { user, refresh } = useAuth();
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
        theme: settings.theme,
      });
      push("Settings saved", "success");
      refresh();
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
    <Layout title="Settings" subtitle="Profile, preferences and account security">
      <div className="card">
        <div className="card-title">Profile</div>
        <Field label="Display name">
          <input className="input" value={displayName} maxLength={120}
                 onChange={(e) => setDisplayName(e.target.value)} />
        </Field>
        <Field label="Email (read-only)">
          <input className="input" value={user?.email || ""} disabled />
        </Field>
        <Field label="Timezone">
          <select
            className="select" value={settings.timezone}
            onChange={(e) => setSettings({ ...settings, timezone: e.target.value })}
          >
            {TIMEZONES.map((tz) => <option key={tz}>{tz}</option>)}
          </select>
        </Field>
        <button className="btn" disabled={busy} onClick={saveProfile}>Save profile</button>
      </div>

      <div className="card">
        <div className="card-title">Change password</div>
        <div className="card-sub">Changing your password signs out all other devices.</div>
        <Field label="Current password">
          <input className="input" type="password" value={pw.current} autoComplete="current-password"
                 onChange={(e) => setPw({ ...pw, current: e.target.value })} />
        </Field>
        <Field label="New password (10+ chars, mixed case or digits)">
          <input className="input" type="password" value={pw.next} autoComplete="new-password"
                 onChange={(e) => setPw({ ...pw, next: e.target.value })} />
        </Field>
        <Field label="Confirm new password">
          <input className="input" type="password" value={pw.confirm} autoComplete="new-password"
                 onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
        </Field>
        <button className="btn" disabled={busy || !pw.current || !pw.next} onClick={changePassword}>
          Change password
        </button>
      </div>

      <div className="card">
        <div className="card-title">About</div>
        <div className="small muted">
          MANISK · Personal AI Operating System · v0.1.0<br />
          Conversational AI · personal memory · planning · tools · permission firewall · automations.<br />
          Your data (conversations, memories, tasks, files) is isolated to your account and never
          shared. Secrets and API keys are kept server-side only.
        </div>
      </div>
    </Layout>
  );
}
