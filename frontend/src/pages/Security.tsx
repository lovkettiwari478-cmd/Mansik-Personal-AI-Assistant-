/* Security Center v2 — emergency stop, pending confirmations,
 * permission grants, sessions/devices, password, audit preview. */

import { useCallback, useEffect, useState } from "react";
import { activityApi, authApi, confirmationApi, fmtDate, securityApi } from "../api";
import { useToast } from "../state";
import { Badge, Loading, riskBadge } from "../components/ui";
import Layout from "../components/Layout";

export default function SecurityPage() {
  const { push } = useToast();
  const [permissions, setPermissions] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [confirmations, setConfirmations] = useState<any[]>([]);
  const [activity, setActivity] = useState<any[]>([]);
  const [emergency, setEmergency] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });

  const load = useCallback(async () => {
    try {
      const [p, s, e, c, a] = await Promise.all([
        securityApi.permissions(), authApi.sessions(), securityApi.emergencyStopStatus(),
        confirmationApi.pending(), activityApi.list(),
      ]);
      setPermissions(p.permissions);
      setSessions(s.sessions);
      setEmergency(e.active);
      setConfirmations(c.confirmations);
      setActivity(a.activity.slice(0, 8));
    } catch (err: any) {
      push(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, [push]);

  useEffect(() => { load(); }, [load]);

  const setGrant = async (scope: string, allowed: boolean) => {
    setBusy(true);
    try {
      await securityApi.setPermission(scope, allowed);
      push(`"${scope}" ${allowed ? "granted" : "denied"}`, "success");
      load();
    } catch (e: any) { push(e.message, "error"); }
    finally { setBusy(false); }
  };

  const revoke = async (scope: string) => {
    setBusy(true);
    try {
      await securityApi.revokePermission(scope);
      push(`"${scope}" reset (asks per-action again)`, "success");
      load();
    } catch (e: any) { push(e.message, "error"); }
    finally { setBusy(false); }
  };

  const toggleEmergency = async () => {
    const next = !emergency;
    if (next && !confirm("Activate EMERGENCY STOP? All tool execution and automations halt immediately.")) return;
    setBusy(true);
    try {
      const r = await securityApi.emergencyStop(next);
      setEmergency(r.active);
      push(r.active ? "🛑 Emergency stop ACTIVE" : "Emergency stop released", r.active ? "error" : "success");
      load();
    } catch (e: any) { push(e.message, "error"); }
    finally { setBusy(false); }
  };

  const actConfirmation = async (id: string, approve: boolean) => {
    setBusy(true);
    try {
      if (approve) {
        const r = await confirmationApi.approve(id);
        push(r.result?.summary || "Executed", r.result?.success === false ? "error" : "success");
      } else {
        await confirmationApi.deny(id);
        push("Denied", "info");
      }
      load();
    } catch (e: any) { push(e.message, "error"); }
    finally { setBusy(false); }
  };

  const revokeSession = async (id: string) => {
    try {
      await authApi.revokeSession(id);
      push("Session revoked", "success");
      load();
    } catch (e: any) { push(e.message, "error"); }
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
    <Layout title="Security" subtitle="Permission firewall · emergency stop · devices · audit">
      {/* emergency stop */}
      <div className={`estop ${emergency ? "active" : ""}`}>
        <div className="row between">
          <div className="grow">
            <div className="card-title" style={{ color: emergency ? "var(--danger)" : undefined, fontSize: 16 }}>
              🛑 Emergency Stop
            </div>
            <div className="small muted">
              Instantly halts ALL tool execution and automations. Reads keep working.
              {emergency && <strong style={{ color: "var(--danger)" }}> — CURRENTLY ACTIVE</strong>}
            </div>
          </div>
          <button className={`estop-btn ${emergency ? "armed" : ""}`} style={{ width: "auto", padding: "10px 22px" }}
                  disabled={busy} onClick={toggleEmergency}>
            {emergency ? "◼ RELEASE" : "◉ ACTIVATE"}
          </button>
        </div>
      </div>

      {/* pending confirmations */}
      {confirmations.length > 0 && (
        <div className="card mt-14" style={{ borderColor: "rgba(245,181,68,0.4)" }}>
          <div className="card-title">Pending confirmations ({confirmations.length})</div>
          <div className="card-sub">Actions MANISK proposed that need your explicit approval.</div>
          {confirmations.map((c) => (
            <div key={c.id} className="list-item" style={{ borderColor: "rgba(245,181,68,0.3)" }}>
              <div className="grow">
                <div className="row wrap">
                  <span className="mono small" style={{ fontWeight: 600 }}>{c.tool_id}</span>
                  <Badge kind="warning">{(c.risk || "").replace(/_/g, " ")}</Badge>
                </div>
                <div className="small muted mt-8">{c.reason}</div>
                <div className="confirm-params">{JSON.stringify(c.params, null, 2)}</div>
                <div className="small faint">expires {fmtDate(c.expires_at)}</div>
              </div>
              <div className="row">
                <button className="btn small" disabled={busy} onClick={() => actConfirmation(c.id, true)}>Approve</button>
                <button className="btn secondary small" disabled={busy} onClick={() => actConfirmation(c.id, false)}>Deny</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {loading ? <div className="mt-14"><Loading /></div> : (
        <>
          {/* permission scopes */}
          <div className="card mt-14">
            <div className="card-title">Permission scopes</div>
            <div className="card-sub">
              Standing grants let tools act without asking each time. Deny blocks a scope entirely.
              Without a grant, high-risk and external actions require a fresh confirmation (expires in 10 min).
            </div>
            {permissions.map((p) => (
              <div key={p.scope} className="list-item">
                <div className="grow">
                  <div className="row wrap">
                    <strong>{p.label}</strong>
                    {riskBadge(p.risk)}
                    {p.granted && <Badge kind="success">granted</Badge>}
                    {p.denied && <Badge kind="danger">denied</Badge>}
                    {!p.granted && !p.denied && <Badge>ask each time</Badge>}
                  </div>
                  <div className="small muted mt-8">{p.description}</div>
                </div>
                <div className="row">
                  <button className="btn secondary small" disabled={busy} onClick={() => setGrant(p.scope, true)}>Grant</button>
                  <button className="btn secondary small" disabled={busy} onClick={() => setGrant(p.scope, false)}>Deny</button>
                  {(p.granted || p.denied) && (
                    <button className="btn ghost small" disabled={busy} onClick={() => revoke(p.scope)}>Reset</button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* devices */}
          <div className="card mt-14">
            <div className="card-title">Devices & sessions</div>
            <div className="card-sub">Signed-in devices. Revoke anything you don't recognize.</div>
            {sessions.map((s) => (
              <div key={s.id} className="list-item">
                <div className="grow">
                  <div className="row wrap">
                    <span style={{ fontWeight: 600 }}>
                      {s.user_agent ? s.user_agent.slice(0, 55) : "Unknown client"}
                    </span>
                    {s.current && <Badge kind="success">this device</Badge>}
                  </div>
                  <div className="small faint">
                    {s.ip || "unknown IP"} · last seen {fmtDate(s.last_seen_at)}
                  </div>
                </div>
                {!s.current && (
                  <button className="btn secondary small" onClick={() => revokeSession(s.id)}>Revoke</button>
                )}
              </div>
            ))}
            <button className="btn secondary small mt-8" onClick={async () => {
              if (!confirm("Sign out from ALL devices (including this one)?")) return;
              await authApi.logoutAll();
              window.location.href = "/login";
            }}>
              Sign out everywhere
            </button>
          </div>

          {/* password */}
          <div className="card mt-14">
            <div className="card-title">Password</div>
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

          {/* audit preview */}
          <div className="card mt-14">
            <div className="row between mb-14">
              <div className="card-title">Recent security-relevant activity</div>
            </div>
            {activity.map((a) => (
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
        </>
      )}
    </Layout>
  );
}
