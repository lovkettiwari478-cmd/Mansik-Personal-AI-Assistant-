/* Integrations page — honest status of every external capability. */

import { useEffect, useState } from "react";
import { statusApi } from "../api";
import { useStatus } from "../state";
import { Badge, Loading } from "../components/ui";
import Layout from "../components/Layout";

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
    <Layout title="Integrations" subtitle="What MANISK can actually reach right now — no fake connection states">
      {loading ? <Loading /> : (
        <>
          {integrations.map((i) => (
            <div key={i.id} className="card">
              <div className="row between">
                <div className="grow">
                  <div className="row">
                    <strong style={{ fontSize: 15 }}>{i.name}</strong>
                    <Badge kind={i.configured ? "success" : "warning"}>
                      {i.configured ? "configured" : "not configured"}
                    </Badge>
                  </div>
                  <div className="small muted mt-8">{i.description}</div>
                  <div className="small faint mt-8 mono">
                    {i.required_env.map((v: string) => (
                      <div key={v}>{v}</div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}

          <div className="card">
            <div className="card-title">Tool catalog</div>
            <div className="card-sub">
              Every tool MANISK can execute — with its risk class, permission scope and availability.
              Unavailable tools are shown honestly (missing credentials or disabled in this deployment).
            </div>
            {tools.map((t: any) => (
              <div key={t.id} className="list-item">
                <div className="grow">
                  <div className="row wrap">
                    <span className="mono" style={{ fontWeight: 600 }}>{t.id}</span>
                    {!t.available && <Badge kind="danger">unavailable</Badge>}
                  </div>
                  <div className="small muted mt-8">{t.description}</div>
                  {t.unavailable_reason && (
                    <div className="small" style={{ color: "var(--warning)" }}>⚠ {t.unavailable_reason}</div>
                  )}
                </div>
                <div className="small faint mono" style={{ textAlign: "right" }}>
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
