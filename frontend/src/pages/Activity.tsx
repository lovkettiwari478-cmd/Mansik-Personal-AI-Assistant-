/* Activity page — the user's audit trail. */

import { useCallback, useEffect, useState } from "react";
import { activityApi, fmtDate } from "../api";
import { Badge } from "../components/ui";
import Layout from "../components/Layout";
import { EmptyState, Loading } from "../components/ui";

const CATEGORIES = ["all", "auth", "security", "tool", "memory", "task", "calendar", "automation", "file"];

export default function ActivityPage() {
  const [entries, setEntries] = useState<any[]>([]);
  const [category, setCategory] = useState("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await activityApi.list(category === "all" ? undefined : category);
      setEntries(r.activity);
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => { load(); }, [load]);

  return (
    <Layout title="Activity" subtitle="Every sensitive action is audited — you can see exactly what happened and when">
      <div className="seg mb-14" style={{ overflowX: "auto" }}>
        {CATEGORIES.map((c) => (
          <button key={c} className={`seg-btn ${category === c ? "active" : ""}`} onClick={() => setCategory(c)}>
            {c}
          </button>
        ))}
      </div>

      {loading ? <Loading /> : entries.length === 0 ? (
        <EmptyState icon="🗒" title="No activity yet" />
      ) : (
        entries.map((a) => (
          <div key={a.id} className={`feed-item ${a.category === "security" ? "security" : a.category}`}>
            <div className="row wrap">
              <Badge kind={a.category === "security" ? "warning" : a.category === "auth" ? "info" : ""}>
                {a.category}
              </Badge>
              <span style={{ fontWeight: 600, fontSize: 14 }}>{a.action}</span>
            </div>
            <div className="small muted">{a.event_type}{a.resource ? ` · ${a.resource.slice(0, 40)}` : ""}</div>
            <div className="feed-time">
              {fmtDate(a.created_at)}{a.ip ? ` · ${a.ip}` : ""} · {a.request_id || "—"}
            </div>
          </div>
        ))
      )}
    </Layout>
  );
}
