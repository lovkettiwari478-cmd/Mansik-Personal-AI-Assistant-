/* Integrations v2 — honest state of every external capability.
 * No fake "Connected" badges; missing credentials are shown with the
 * exact environment variables required. */

import { useEffect, useState } from "react";
import { statusApi } from "../api";
import { useStatus } from "../state";
import { Badge, Loading } from "../components/ui";
import Layout from "../components/Layout";

const INTEGRATION_META: Record<string, { icon: string; name: string }> = {
  "ai-provider": { icon: "❖", name: "AI Model Provider" },
  "web-search": { icon: "⌕", name: "Web Search" },
  email: { icon: "✉", name: "Email (SMTP)" },
};

export default function IntegrationsPage() {
  const { refresh } = useStatus();
  const [integrations, setIntegrations] = useState<any[]>([]);
  const [tools, setTools] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [i, t] = await Promise.all([statusApi.integrations(), statusApi.tools()]);
        setIntegrations(i.integrations);
        setTools(t.tools);
      } finally {
        setLoading(false);
      }
      refresh();
    })();
  }, [refresh]);

  return (
    <Layout title="Integrations" subtitle="What MANISK can actually reach right now — honestly reported">
      {loading ? <Loading /> : (
        <>
          {integrations.map((i) => {
            const meta = INTEGRATION_META[i.id] || { icon: "⬡", name: i.name };
            return (
              <div key={i.id} className="card hoverable">
                <div className="row top">
                  <div className={`integration-icon ${i.configured ? "on" : ""}`} aria-hidden>
                    {meta.icon}
                  </div>
                  <div className="grow">
                    <div className="row wrap">
                      <strong style={{ fontSize: 14.5 }}>{meta.name}</strong>
                      <Badge kind={i.configured ? "success" : "warning"}>
                        {i.configured ? "configured" : "not connected"}
                      </Badge>
                    </div>
                    <div className="small muted mt-8">{i.description}</div>
                    {!i.configured && (
                      <div className="small mt-8" style={{ color: "var(--text-3)" }}>
                        Required configuration (server-side environment variables):
                        <div className="mono mt-8" style={{ color: "var(--warning)" }}>
                          {i.required_env.map((v: string) => <div key={v}>{v}</div>)}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}

          <div className="card mt-14">
            <div className="card-title">Tool catalog</div>
            <div className="card-sub">
              Every tool MANISK can execute — risk class, permission scope and honest availability.
            </div>
            {tools.map((t: any) => (
              <div key={t.id} className="list-item">
                <div className="grow">
                  <div className="row wrap">
                    <span className="mono" style={{ fontWeight: 600, fontSize: 12.5 }}>{t.id}</span>
                    {!t.available && <Badge kind="danger">unavailable</Badge>}
                  </div>
                  <div className="small muted mt-8">{t.description}</div>
                  {t.unavailable_reason && (
                    <div className="small" style={{ color: "var(--warning)" }}>⚠ {t.unavailable_reason}</div>
                  )}
                </div>
                <div className="small faint mono" style={{ textAlign: "right", flexShrink: 0 }}>
                  <div>risk: {t.risk}</div>
                  <div>scope: {t.scope || "—"}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Layout>
  );
}
