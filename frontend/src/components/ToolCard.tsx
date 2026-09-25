/* ToolCard — friendly execution status + rich result cards.
 * Shows what MANISK is doing in user terms ("Creating task…"),
 * which agent role handled it, and renders structured results
 * (task created, memory saved, event scheduled, search results). */

import { Badge, Spinner } from "./ui";
import { fmtDate } from "../api";

export interface ToolEventState {
  tool: string;
  name?: string;
  label?: string;
  agent?: string;
  state: "running" | "ok" | "fail";
  summary?: string;
  verified?: boolean;
  output?: any;
}

function ResultCard({ tool, output }: { tool: string; output: any }) {
  if (!output) return null;

  if (tool === "tasks.create" && output.task) {
    const t = output.task;
    return (
      <div className="tool-result-card">
        <div className="row between">
          <span className="rr-title">✓ {t.title}</span>
          <Badge kind={t.priority === "urgent" ? "danger" : t.priority === "high" ? "warning" : "info"}>
            {t.priority}
          </Badge>
        </div>
        {t.due_at && <div className="rr-sub">Due {fmtDate(t.due_at)}</div>}
        {output.verified && <div className="rr-sub faint">✓ verified in database</div>}
      </div>
    );
  }
  if (tool === "tasks.complete" && output.task) {
    return (
      <div className="tool-result-card">
        <div className="rr-title">✓ Completed: {output.task.title}</div>
      </div>
    );
  }
  if (tool === "memory.save" && output.memory) {
    const m = output.memory;
    return (
      <div className="tool-result-card">
        <div className="rr-title">🧠 Saved to memory</div>
        <div className="rr-sub">“{m.content}”</div>
        <div className="rr-sub faint">
          {m.kind} · {m.source} {output.verified ? "· ✓ verified" : ""}
        </div>
      </div>
    );
  }
  if (tool === "calendar.create_event" && output.event) {
    const e = output.event;
    return (
      <div className="tool-result-card">
        <div className="rr-title">📅 {e.title}</div>
        <div className="rr-sub">{fmtDate(e.starts_at)}{e.location ? ` · ${e.location}` : ""}</div>
        {output.conflicts && (
          <div className="rr-sub" style={{ color: "var(--warning)" }}>
            ⚠ overlaps {output.conflicts.length} existing event(s)
          </div>
        )}
        {output.verified && <div className="rr-sub faint">✓ verified in calendar</div>}
      </div>
    );
  }
  if (tool === "web.search" && output.results) {
    return (
      <div className="tool-result-card">
        <div className="rr-title">Search results</div>
        {output.results.slice(0, 5).map((r: any, i: number) => (
          <a key={i} className="rr-link" href={r.url} target="_blank" rel="noreferrer noopener">
            {i + 1}. {r.title || r.url}
          </a>
        ))}
      </div>
    );
  }
  if (tool === "time.now") {
    return (
      <div className="tool-result-card">
        <div className="rr-title">{output.weekday}, {output.date}</div>
        <div className="rr-sub">{output.time} ({output.timezone})</div>
      </div>
    );
  }
  return null;
}

export default function ToolCard({ ev }: { ev: ToolEventState }) {
  return (
    <>
      <div className={`tool-card ${ev.state === "running" ? "running" : ev.state}`}>
        {ev.state === "running" ? <Spinner /> : ev.state === "ok" ? "✓" : "✕"}
        <span style={{ fontWeight: 600, color: "var(--text)" }}>
          {ev.state === "running"
            ? ev.label || ev.name || ev.tool
            : ev.summary || ev.label || ev.tool}
        </span>
        {ev.agent && ev.agent !== "Core" && <span className="tool-agent">{ev.agent}</span>}
      </div>
      {ev.state !== "running" && ev.state === "ok" && (
        <ResultCard tool={ev.tool} output={ev.output} />
      )}
    </>
  );
}
