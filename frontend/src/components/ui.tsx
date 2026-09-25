/* Shared UI primitives. */

import React from "react";

export function Spinner() {
  return <span className="spinner" role="status" aria-label="Loading" />;
}

export function Badge({ kind, children }: { kind?: string; children: React.ReactNode }) {
  return <span className={`badge ${kind || ""}`}>{children}</span>;
}

export function EmptyState({ icon, title, hint }: { icon: string; title: string; hint?: string }) {
  return (
    <div className="empty">
      <div className="big" aria-hidden>{icon}</div>
      <div style={{ fontWeight: 600, color: "var(--text-dim)", marginBottom: 4 }}>{title}</div>
      {hint && <div className="small">{hint}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="center muted" style={{ padding: 40 }}>
      <Spinner /> <span style={{ marginLeft: 8 }}>{label}</span>
    </div>
  );
}

export function Modal({
  title, onClose, children, wide,
}: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="modal" style={wide ? { maxWidth: 620 } : undefined}>
        <div className="row between mb-14">
          <div style={{ fontWeight: 700, fontSize: 16 }}>{title}</div>
          <button className="btn ghost small" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Toggle({
  on, onChange, label, description,
}: { on: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  return (
    <div className="row between" style={{ padding: "9px 0" }}>
      <div className="grow">
        <div style={{ fontWeight: 600, fontSize: 14 }}>{label}</div>
        {description && <div className="small faint">{description}</div>}
      </div>
      <button
        className={`toggle ${on ? "on" : ""}`}
        onClick={() => onChange(!on)}
        aria-pressed={on}
        aria-label={label}
      />
    </div>
  );
}

export function Field({
  label, children,
}: { label: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
    </div>
  );
}

export function riskBadge(risk: string) {
  const map: Record<string, [string, string]> = {
    read: ["success", "read"],
    low_risk_write: ["info", "low-risk write"],
    high_risk_write: ["warning", "high-risk write"],
    external_communication: ["warning", "external communication"],
    financial: ["danger", "financial"],
    security: ["danger", "security"],
    device_control: ["danger", "device control"],
  };
  const [kind, text] = map[risk] || ["", risk];
  return <Badge kind={kind}>{text}</Badge>;
}

/* Minimal markdown renderer for chat bubbles: **bold**, `code`,
 * [links], and line breaks. Deliberately tiny — no HTML injection
 * because we never build HTML strings. */
export function renderRichText(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) {
      parts.push(<strong key={key++}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("`")) {
      parts.push(<code key={key++}>{tok.slice(1, -1)}</code>);
    } else {
      const label = tok.slice(1, tok.indexOf("]"));
      const href = tok.slice(tok.indexOf("(") + 1, -1);
      parts.push(
        <a key={key++} href={href} target="_blank" rel="noreferrer noopener">{label}</a>,
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
