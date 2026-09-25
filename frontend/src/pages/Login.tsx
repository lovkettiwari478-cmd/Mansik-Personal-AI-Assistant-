/* Login / Register screen. */

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth, useToast } from "../state";
import { Field, Spinner } from "../components/ui";

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { login, register } = useAuth();
  const { push } = useToast();
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password, displayName || email.split("@")[0]);
      }
      push(`Welcome${mode === "register" ? " to MANISK" : " back"}!`, "success");
      navigate("/chat");
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-head">
          <div className="brand-logo">M</div>
          <div className="auth-title">MANISK</div>
          <div className="auth-sub">Your Personal AI Operating System</div>
        </div>
        <div className="card">
          <form onSubmit={submit}>
            {mode === "register" && (
              <Field label="Display name">
                <input
                  className="input" value={displayName} autoComplete="name"
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="How should I call you?" maxLength={120}
                />
              </Field>
            )}
            <Field label="Email">
              <input
                className="input" type="email" required value={email}
                autoComplete="email" onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </Field>
            <Field label="Password">
              <input
                className="input" type="password" required value={password}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "register" ? "10+ chars, mixed case or digits" : "••••••••"}
              />
            </Field>
            {error && (
              <div className="small" style={{ color: "var(--danger)", marginBottom: 10 }} role="alert">
                {error}
              </div>
            )}
            <button className="btn" style={{ width: "100%" }} disabled={busy}>
              {busy ? <Spinner /> : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
          <div className="center small mt-14">
            <span className="muted">
              {mode === "login" ? "New to MANISK?" : "Already have an account?"}{" "}
            </span>
            <a
              href="#"
              onClick={(e) => { e.preventDefault(); setMode(mode === "login" ? "register" : "login"); setError(""); }}
            >
              {mode === "login" ? "Create an account" : "Sign in"}
            </a>
          </div>
        </div>
        <div className="center faint small mt-14">
          Private by design · your data stays in your account
        </div>
      </div>
    </div>
  );
}
