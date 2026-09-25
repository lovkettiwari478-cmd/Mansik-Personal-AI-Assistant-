/* App shell v2: glass sidebar (desktop), drawer + bottom nav (mobile). */

import React, { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth, useNotifications, useStatus } from "../state";
import { Badge } from "./ui";
import Orb from "./Orb";

const NAV_MAIN = [
  { to: "/", label: "Home", icon: "◈", exact: true },
  { to: "/chat", label: "Chat", icon: "❖" },
];
const NAV_WORK = [
  { to: "/tasks", label: "Tasks", icon: "✓" },
  { to: "/calendar", label: "Calendar", icon: "▤" },
  { to: "/memory", label: "Memory", icon: "◉" },
  { to: "/automations", label: "Automations", icon: "⚡" },
  { to: "/files", label: "Files", icon: "▦" },
];
const NAV_SYSTEM = [
  { to: "/activity", label: "Activity", icon: "≡" },
  { to: "/security", label: "Security", icon: "⛨" },
  { to: "/integrations", label: "Integrations", icon: "⬡" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const { unread } = useNotifications();
  return (
    <>
      <div className="nav-section">Command</div>
      {NAV_MAIN.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.exact}
                 className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                 onClick={onNavigate}>
          <span className="nav-icon" aria-hidden>{n.icon}</span> {n.label}
        </NavLink>
      ))}
      <div className="nav-section">Workspace</div>
      {NAV_WORK.map((n) => (
        <NavLink key={n.to} to={n.to}
                 className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                 onClick={onNavigate}>
          <span className="nav-icon" aria-hidden>{n.icon}</span> {n.label}
        </NavLink>
      ))}
      <div className="nav-section">System</div>
      {NAV_SYSTEM.map((n) => (
        <NavLink key={n.to} to={n.to}
                 className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                 onClick={onNavigate}>
          <span className="nav-icon" aria-hidden>{n.icon}</span> {n.label}
          {n.to === "/security" && unread > 0 && <span className="nav-badge">{unread}</span>}
        </NavLink>
      ))}
    </>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { aiConfigured } = useStatus();
  return (
    <aside className="sidebar" aria-label="Main navigation">
      <div className="brand">
        <div className="brand-mark">M</div>
        <div>
          <div className="brand-name">MANISK</div>
          <div className="brand-sub">Personal AI OS</div>
        </div>
      </div>
      <NavItems onNavigate={onNavigate} />
      <div className="sidebar-footer">
        <div className="row between mb-8" style={{ paddingLeft: 10 }}>
          <div className="small muted" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {user?.display_name}
          </div>
          <Badge kind={aiConfigured ? "success" : "warning"}>{aiConfigured ? "AI" : "Local"}</Badge>
        </div>
        <button
          className="btn ghost small"
          style={{ width: "100%" }}
          onClick={async () => { await logout(); navigate("/login"); }}
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}

const MOBILE_NAV = [
  { to: "/", label: "Home", icon: "◈", exact: true },
  { to: "/chat", label: "Chat", icon: "❖" },
  { to: "/tasks", label: "Tasks", icon: "✓" },
  { to: "/memory", label: "Memory", icon: "◉" },
  { to: "/security", label: "Security", icon: "⛨" },
];

export default function Layout({ children, title, subtitle, fullscreen }: {
  children: React.ReactNode;
  title: string;
  subtitle?: string;
  fullscreen?: boolean;
}) {
  const [drawer, setDrawer] = useState(false);
  const { aiConfigured, aiModel } = useStatus();

  return (
    <div className="app-shell">
      <Sidebar />
      {drawer && (
        <div className="drawer" onClick={(e) => { if (e.target === e.currentTarget) setDrawer(false); }}>
          <Sidebar onNavigate={() => setDrawer(false)} />
        </div>
      )}
      <div className="main">
        <div className="mobile-top">
          <button className="btn ghost small" onClick={() => setDrawer(true)} aria-label="Open menu">☰</button>
          <div className="row" style={{ gap: 8 }}>
            <Orb state="idle" size={20} />
            <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.05em" }}>MANISK</span>
          </div>
          <button className="btn ghost small" onClick={() => setDrawer(true)} aria-label="More">⋯</button>
        </div>
        <div className="topbar">
          <div style={{ minWidth: 0 }}>
            <div className="topbar-title">{title}</div>
            {subtitle && <div className="topbar-sub">{subtitle}</div>}
          </div>
          <div style={{ marginLeft: "auto" }} className="row">
            {aiConfigured && aiModel && (
              <span className="faint small mono" title="Active AI model">{aiModel}</span>
            )}
            <Orb state={aiConfigured ? "idle" : "idle"} size={26} />
          </div>
        </div>
        {fullscreen ? (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>{children}</div>
        ) : (
          <div className="content">{children}</div>
        )}
        <nav className="bottom-nav" aria-label="Quick navigation">
          {MOBILE_NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.exact}
                     className={({ isActive }) => `bottom-nav-item ${isActive ? "active" : ""}`}>
              <span aria-hidden>{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
