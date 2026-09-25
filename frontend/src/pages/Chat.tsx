/* Chat v2 — the heart of MANISK.
 * Streaming, markdown, tool cards, confirmations, stop/retry,
 * conversation history, mobile keyboard friendly. */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { conversationApi, confirmationApi, settingsApi, streamChat } from "../api";
import { useAuth, useStatus, useToast } from "../state";
import { Badge, Spinner } from "../components/ui";
import Layout from "../components/Layout";
import Orb, { OrbState } from "../components/Orb";
import Markdown from "../components/Markdown";
import ToolCard, { ToolEventState } from "../components/ToolCard";

interface ChatMsg {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools?: ToolEventState[];
  mode?: string;
  memoriesUsed?: any[];
  streaming?: boolean;
  error?: boolean;
  aborted?: boolean;
}

interface Conversation {
  id: string;
  title: string;
  updated_at: string;
}

function ConfirmationCard({
  confirmation, onResolved,
}: { confirmation: any; onResolved: () => void }) {
  const [busy, setBusy] = useState(false);
  const { push } = useToast();
  const expired = new Date(confirmation.expires_at) < new Date();

  const act = async (approve: boolean) => {
    setBusy(true);
    try {
      if (approve) {
        const r = await confirmationApi.approve(confirmation.id ?? confirmation.confirmation_id);
        push(r.result?.summary || "Action executed", r.result?.success === false ? "error" : "success");
      } else {
        await confirmationApi.deny(confirmation.id ?? confirmation.confirmation_id);
        push("Action denied", "info");
      }
      onResolved();
    } catch (e: any) {
      push(e.message || "Failed", "error");
    } finally {
      setBusy(false);
    }
  };

  if (expired || ["executed", "denied", "failed", "expired"].includes(confirmation.status)) {
    return (
      <div className="confirm-card" style={{ opacity: 0.7 }}>
        <div className="confirm-title">Confirmation {confirmation.status || "expired"}</div>
      </div>
    );
  }

  return (
    <div className="confirm-card" role="alertdialog" aria-label="Action confirmation">
      <div className="confirm-title">
        ⚠ Confirm action
        <Badge kind="warning">{(confirmation.risk || "").replace(/_/g, " ")}</Badge>
      </div>
      <div className="small mt-8">{confirmation.reason || confirmation.tool_name || confirmation.tool}</div>
      <div className="confirm-params">
        {confirmation.tool}
        {confirmation.params ? `\n${JSON.stringify(confirmation.params, null, 2)}` : ""}
      </div>
      <div className="row wrap">
        <button className="btn small" disabled={busy} onClick={() => act(true)}>
          {busy ? <Spinner /> : "Approve & run"}
        </button>
        <button className="btn secondary small" disabled={busy} onClick={() => act(false)}>Deny</button>
        <span className="faint small">expires {new Date(confirmation.expires_at).toLocaleTimeString()}</span>
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { user } = useAuth();
  const { aiConfigured } = useStatus();
  const { push } = useToast();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [orbState, setOrbState] = useState<OrbState>("idle");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [pendingConfirm, setPendingConfirm] = useState<any | null>(null);
  const [assistantName, setAssistantName] = useState("MANISK");
  const [lastFailedText, setLastFailedText] = useState<string | null>(null);
  const location = useLocation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const scrollDown = useCallback((smooth = false) => {
    requestAnimationFrame(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTo({
          top: scrollRef.current.scrollHeight,
          behavior: smooth ? "smooth" : "auto",
        });
      }
    });
  }, []);

  useEffect(() => {
    settingsApi.get().then((s) => setAssistantName(s.assistant_name || "MANISK")).catch(() => {});
    // prefill draft from quick actions (Home) if provided
    const draft = (location.state as any)?.draft;
    if (draft) {
      setInput(draft);
      window.history.replaceState({}, "");
    }
  }, [location.state]);

  const loadConversations = useCallback(async () => {
    try {
      const r = await conversationApi.list();
      setConversations(r.conversations);
    } catch { /* ignore */ }
  }, []);

  const loadMessages = useCallback(async (id: string) => {
    try {
      const r = await conversationApi.messages(id);
      setMessages(r.messages.map((m: any) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        tools: (m.meta?.tools || []).map((t: any) => ({
          tool: t.id, state: t.success ? "ok" : "fail", summary: t.summary,
        })),
        mode: m.meta?.mode,
        aborted: m.meta?.aborted,
        memoriesUsed: [],
      })));
      setConversationId(id);
      setPendingConfirm(null);
      scrollDown();
    } catch (e: any) {
      push(e.message, "error");
    }
  }, [push, scrollDown]);

  useEffect(() => { loadConversations(); }, [loadConversations]);

  useEffect(() => {
    if (!conversationId && conversations.length > 0 && messages.length === 0) {
      loadMessages(conversations[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations]);

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
  };

  const send = async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || sending) return;
    setInput("");
    setSending(true);
    setLastFailedText(null);
    setOrbState("thinking");

    const userMsg: ChatMsg = { id: `u-${Date.now()}`, role: "user", content: text };
    const aiMsg: ChatMsg = {
      id: `a-${Date.now()}`, role: "assistant", content: "", streaming: true,
      tools: [], memoriesUsed: [],
    };
    setMessages((m) => [...m, userMsg, aiMsg]);
    scrollDown(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const setMsg = (fn: (m: ChatMsg) => ChatMsg) =>
      setMessages((ms) => ms.map((x) => (x.id === aiMsg.id ? fn(x) : x)));

    try {
      await streamChat(text, conversationId, (ev) => {
        if (ev.event === "meta") {
          aiMsg.mode = ev.mode;
          aiMsg.memoriesUsed = ev.memories_used || [];
          setMsg(() => ({ ...aiMsg }));
        } else if (ev.event === "delta") {
          aiMsg.content += ev.text;
          setMsg(() => ({ ...aiMsg }));
          scrollDown();
        } else if (ev.event === "tool_start") {
          setOrbState("tool");
          aiMsg.tools = [...(aiMsg.tools || []), {
            tool: ev.tool, name: ev.name, label: ev.label, agent: ev.agent, state: "running",
          }];
          setMsg(() => ({ ...aiMsg }));
          scrollDown(true);
        } else if (ev.event === "tool_end") {
          aiMsg.tools = (aiMsg.tools || []).map((t) =>
            t.tool === ev.tool && t.state === "running"
              ? {
                  ...t, state: ev.success ? "ok" : "fail", summary: ev.summary,
                  verified: ev.verified, output: ev.output,
                }
              : t,
          );
          setMsg(() => ({ ...aiMsg }));
        } else if (ev.event === "confirmation_required") {
          setPendingConfirm(ev);
          setOrbState("waiting");
          setMsg(() => ({ ...aiMsg }));
        } else if (ev.event === "error") {
          aiMsg.content += (aiMsg.content ? "\n\n" : "") + `⚠️ ${ev.message}`;
          aiMsg.error = true;
          setMsg(() => ({ ...aiMsg }));
        } else if (ev.event === "done") {
          aiMsg.streaming = false;
          if (ev.conversation_id) setConversationId(ev.conversation_id);
          setMsg(() => ({ ...aiMsg }));
        }
      }, controller.signal);
      setOrbState(pendingConfirm ? "waiting" : "done");
      setTimeout(() => setOrbState("idle"), 2600);
    } catch (e: any) {
      const aborted = e.name === "AbortError";
      aiMsg.streaming = false;
      aiMsg.aborted = aborted;
      if (!aborted) {
        aiMsg.error = true;
        aiMsg.content += (aiMsg.content ? "\n\n" : "") + `⚠️ ${e.message || "Connection lost."}`;
        setLastFailedText(text);
      }
      setMsg(() => ({ ...aiMsg }));
      setOrbState(aborted ? "idle" : "error");
    } finally {
      setSending(false);
      abortRef.current = null;
      loadConversations();
      try {
        const r = await confirmationApi.pending();
        if (r.confirmations.length > 0) {
          setPendingConfirm(r.confirmations[0]);
          setOrbState("waiting");
        }
      } catch { /* ignore */ }
    }
  };

  const newConversation = () => {
    setMessages([]);
    setConversationId(null);
    setPendingConfirm(null);
    setOrbState("idle");
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const showTyping = sending && messages.length > 0 &&
    messages[messages.length - 1].streaming && !messages[messages.length - 1].content &&
    !(messages[messages.length - 1].tools || []).length;

  return (
    <Layout title={`${assistantName} · Chat`} subtitle="Converse, plan and execute — through the permission firewall" fullscreen>
      <div className="chat-page" style={{ height: "100%" }}>
        <div className="chat-scroll" ref={scrollRef}>
          {conversations.length > 0 && (
            <div className="row wrap mb-14" style={{ justifyContent: "center" }}>
              <button className="btn secondary small" onClick={newConversation}>＋ New</button>
              {conversations.slice(0, 8).map((c) => (
                <button
                  key={c.id}
                  className={`btn small ${c.id === conversationId ? "" : "secondary"}`}
                  onClick={() => loadMessages(c.id)}
                  style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                >
                  {c.title}
                </button>
              ))}
            </div>
          )}

          {!aiConfigured && (
            <div className="mode-banner" role="status">
              <span aria-hidden>◆</span>
              <div>
                <strong>Local Mode.</strong> No AI provider is configured on this deployment — free-form
                AI conversation is unavailable (we don't fake it). Real commands still work: tasks,
                calendar, memory, math, time. Type <code>help</code> for examples.
              </div>
            </div>
          )}
          {aiConfigured && (
            <div className="mode-banner ai" role="status">
              <span aria-hidden>◆</span>
              <div><strong>AI Mode.</strong> Full conversational intelligence with tool execution and permission-gated actions.</div>
            </div>
          )}

          <div className="chat-stream">
            {messages.length === 0 && (
              <div className="empty" style={{ marginTop: 40 }}>
                <div style={{ display: "flex", justifyContent: "center", marginBottom: 14 }}>
                  <Orb state="idle" size={56} />
                </div>
                <div style={{ fontWeight: 600, color: "var(--text-2)", fontSize: 15 }}>
                  Hello {user?.display_name?.split(" ")[0]}, I'm {assistantName}.
                </div>
                <div className="small mt-8">
                  {aiConfigured
                    ? "Ask me anything — or ask me to plan and execute tasks for you."
                    : "Try: “create task Buy groceries due tomorrow 5pm” · “remember that I prefer tea” · “what is 12*(8+4)”"}
                </div>
              </div>
            )}

            {messages.map((m) => (
              <div key={m.id} className={`msg ${m.role}`}>
                <div className="msg-avatar" aria-hidden>
                  {m.role === "user"
                    ? (user?.display_name?.[0] || "U")
                    : <Orb state={m.streaming ? orbState : "idle"} size={20} />}
                </div>
                <div className="msg-body">
                  <div className="msg-meta">
                    {m.role === "user" ? "You" : assistantName}
                    {m.mode === "local" && <span className="mem-chip">local mode</span>}
                    {m.aborted && <span className="mem-chip">stopped</span>}
                    {(m.memoriesUsed || []).slice(0, 3).map((mem: any) => (
                      <span key={mem.id} className="mem-chip" title={mem.content}>
                        ◉ memory · {mem.kind}
                      </span>
                    ))}
                  </div>
                  <div className="msg-bubble">
                    {m.content
                      ? <Markdown text={m.content} />
                      : showTyping && m.streaming
                        ? <span className="typing-dots"><span /><span /><span /></span>
                        : m.streaming ? <Spinner /> : null}
                  </div>
                  {(m.tools || []).map((t, i) => <ToolCard key={i} ev={t} />)}
                  {m.error && (
                    <div className="retry-row">
                      <button className="btn ghost small" onClick={() => send(lastFailedText || m.content)}>
                        ↻ Retry
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {pendingConfirm && (
              <div className="msg assistant">
                <div className="msg-avatar" aria-hidden><Orb state="waiting" size={20} /></div>
                <div className="msg-body">
                  <ConfirmationCard
                    confirmation={pendingConfirm}
                    onResolved={() => {
                      setPendingConfirm(null);
                      setOrbState("idle");
                      if (conversationId) loadMessages(conversationId);
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="chat-composer-wrap">
          <div className="chat-composer">
            <textarea
              value={input}
              placeholder={aiConfigured ? `Message ${assistantName}…` : "Try “help” — or “create task …”"}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              disabled={sending}
              aria-label="Message"
            />
            {sending ? (
              <button className="send-btn stop" onClick={stop} aria-label="Stop generating" title="Stop">
                ■
              </button>
            ) : (
              <button className="send-btn" onClick={() => send()} disabled={!input.trim()} aria-label="Send">
                ➤
              </button>
            )}
          </div>
          <div className="center faint" style={{ fontSize: 10.5, marginTop: 7 }}>
            {orbState !== "idle" && (
              <span className="row" style={{ justifyContent: "center", gap: 6 }}>
                <Orb state={orbState} size={12} />
                {orbState === "thinking" && "Thinking…"}
                {orbState === "tool" && "Working…"}
                {orbState === "waiting" && "Waiting for your confirmation"}
              </span>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}
