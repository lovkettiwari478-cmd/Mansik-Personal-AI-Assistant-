/* Login v2 — cinematic entry: aurora backdrop, glass card,
 * animated identity orb, honest server state. */

import React, { useState } from "react";
import { useAuth, useToast } from "../state";
import Orb from "../components/Orb";

export default function LoginPage() {
  const { login, register } = useAuth();
  const { push } = useToast();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ email: "", password: "", name: "" });
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") await login(form.email, form.password);
      else await register(form.email, form.password, form.name || form.email.split("@")[0]);
      push(mode === "login" ? "Welcome back" : "Account created", "success");
    } catch (err: any) {
      push(err.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-brand">
          <Orb state="idle" size={64} />
        </div>
        <h1 className="login-title">MANISK</h1>
        <p className="login-sub">Your personal AI operating system</p>

        <div className="seg" style={{ width: "100%", marginBottom: 18 }}>
          <button className={`seg-btn ${mode === "login" ? "active" : ""}`}
                  onClick={() => setMode("login")}>Sign in</button>
          <button className={`seg-btn ${mode === "register" ? "active" : ""}`}
                  onClick={() => setMode("register")}>Create account</button>
        </div>

        <form onSubmit={submit}>
          {mode === "register" && (
            <div className="field">
              <label>Your name</label>
              <input
                className="input" required maxLength={120} autoComplete="name"
                placeholder="What should MANISK call you?"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
          )}
          <div className="field">
            <label>Email</label>
            <input
              className="input" type="email" required autoFocus autoComplete="email"
              placeholder="you@example.com" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Password</label>
            <input
              className="input" type="password" required minLength={10}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder={mode === "register" ? "10+ characters" : ""}
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
          </div>
          <button className="btn" style={{ width: "100%" }} disabled={busy}>
            {busy ? <span className="spinner" /> : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <div className="login-foot">
          Private by default · sessions revocable · tool actions behind your permission firewall
        </div>
      </div>
    </div>
  );
}
