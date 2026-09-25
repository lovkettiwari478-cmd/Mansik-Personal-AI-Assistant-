/* Orb — MANISK intelligence state visualization.
   A lightweight, elegant indicator of the assistant's ACTIVITY state
   (not a representation of hidden model thoughts). */

import React from "react";

export type OrbState =
  | "idle"
  | "thinking"
  | "tool"
  | "waiting"
  | "done"
  | "error";

const STATE_LABEL: Record<OrbState, string> = {
  idle: "Idle",
  thinking: "Thinking…",
  tool: "Working…",
  waiting: "Waiting for you",
  done: "Done",
  error: "Error",
};

export default function Orb({
  state = "idle",
  size = 34,
  showLabel = false,
  title,
}: {
  state?: OrbState;
  size?: number;
  showLabel?: boolean;
  title?: string;
}) {
  const lit = state === "thinking" || state === "tool";
  return (
    <div
      className="row"
      style={{ gap: 10 }}
      role="status"
      aria-label={`MANISK state: ${STATE_LABEL[state]}`}
    >
      <div
        className={`orb state-${state} ${lit ? "lit" : ""}`}
        style={{ "--orb-size": `${size}px` } as React.CSSProperties}
        title={title || STATE_LABEL[state]}
      >
        <div className="orb-glow" />
        <div className="orb-ring" />
        <div className="orb-core" />
      </div>
      {showLabel && (
        <span
          className="small"
          style={{ color: state === "error" ? "var(--danger)" : "var(--text-2)", fontWeight: 600 }}
        >
          {STATE_LABEL[state]}
        </span>
      )}
    </div>
  );
}
