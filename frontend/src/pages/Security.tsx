/* Security center — permission scopes, emergency stop, sessions. */

import { useCallback, useEffect, useState } from "react";
import { authApi, fmtDate, securityApi } from "../api";
import { useToast } from "../state";
import { Badge, Loading, riskBadge } from "../components/ui";
import Layout from "../components/Layout";

export default function SecurityPage() {
  const { push } = useToast();
  const [permissions, setPermissions] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [emergency, setEmergency] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, s, e] = await Promise.all([
        securityApi.permissions(), authApi.sessions(), securityApi.emergencyStopStatus(),
      ]);
      setPermissions(p.permissions);
      setSessions(s.sessions);
      setEmergency(e.active);
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
      push(`Scope "${scope}" ${allowed ? "granted" : "denied"}`, "success");
      load();
    } catch (e: any) { push(e.message, "error"); }
    finally { setBusy(false); }
  };

  const revoke = async (scope: string) => {
    setBusy(true);
    try {
      await securityApi.revokePermission(scope);
      push(`Scope "${scope}" reset (will ask per-action again)`, "success");
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
      push(r.active ? "🛑 Emergency stop ACTIVE — everything is halted" : "Emergency stop released", r.active ? "error" : "success");
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

  return (
    <Layout title="Security" subtitle="Permission firewall, emergency stop, device sessions">
      {/* Emergency stop */}
      <div className="card" style={{ borderColor: emergency ? "var(--danger)" : "var(--border)" }}>
        <div className="row between">
          <div className="grow">
            <div className="card-title" style={{ color: emergency ? "var(--danger)" : undefined }}>
              🛑 Emergency stop
            </div>
            <div className="small muted">
              Instantly halts ALL tool execution and automations. Reads keep working. Use this if
              anything feels wrong — you can always release it later.
            </div>
          </div>
          <button className={`btn ${emergency ? "danger" : "secondary"}`} disabled={busy} onClick={toggleEmergency}>
            {emergency ? "Release" : "Activate emergency stop"}
          </button>
        </div>
        {emergency && (
          <div className="small mt-8" style={{ color: "var(--danger)" }}>
            ACTIVE — all actions are being blocked and logged.
          </div>
        )}
      </div>

      {/* Permissions */}
      <div className="card">
        <div className="card-title">Permission scopes</div>
        <div className="card-sub">
          Standing grants let tools act without asking each time. Deny blocks a scope entirely.
          Without a standing grant, high-risk and external actions always require a fresh
          confirmation (they expire after 10 minutes).
        </div>
        {loading ? <Loading /> : permissions.map((p) => (
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
              <div className="small faint mono">{p.scope}</div>
            </div>
            <div className="row">
              <button className="btn secondary small" disabled={busy} onClick={() => setGrant(p.scope, true)}>
                Grant
              </button>
              <button className="btn secondary small" disabled={busy} onClick={() => setGrant(p.scope, false)}>
                Deny
              </button>
              {(p.granted || p.denied) && (
                <button className="btn ghost small" disabled={busy} onClick={() => revoke(p.scope)}>
                  Reset
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Sessions */}
      <div className="card">
        <div className="card-title">Device sessions</div>
        <div className="card-sub">Signed-in devices. Revoke anything you don't recognize.</div>
        {sessions.map((s) => (
          <div key={s.id} className="list-item">
            <div className="grow">
              <div className="row wrap">
                <span style={{ fontWeight: 600 }}>
                  {s.user_agent ? s.user_agent.slice(0, 60) : "Unknown client"}
                </span>
                {s.current && <Badge kind="success">this device</Badge>}
              </div>
              <div className="small faint">
                {s.ip || "unknown IP"} · last seen {fmtDate(s.last_seen_at)} · expires {fmtDate(s.expires_at)}
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
    </Layout>
  );
}
