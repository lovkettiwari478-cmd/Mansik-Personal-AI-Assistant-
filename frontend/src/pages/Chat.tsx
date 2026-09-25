/* Chat page — SSE streaming, tool activity, confirmation cards,
 * conversation history. */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { conversationApi, confirmationApi, streamChat } from "../api";
import { useAuth, useStatus, useToast } from "../state";
import { Badge, renderRichText, Spinner } from "../components/ui";
import Layout from "../components/Layout";

interface ToolChip {
  tool: string;
  name?: string;
  state: "running" | "ok" | "fail";
  summary?: string;
}

interface ChatMsg {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools?: ToolChip[];
  confirmation?: any | null;
  mode?: string;
  memoriesUsed?: any[];
  streaming?: boolean;
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

  if (expired || confirmation.status === "executed" || confirmation.status === "denied") {
    return (
      <div className="confirm-card">
        <div className="confirm-title">Confirmation {confirmation.status || "expired"}</div>
      </div>
    );
  }

  return (
    <div className="confirm-card" role="alertdialog" aria-label="Action confirmation">
      <div className="confirm-title">
        ⚠️ Confirm action
        <Badge kind="warning">{(confirmation.risk || "").replace(/_/g, " ")}</Badge>
      </div>
      <div className="small mt-8">{confirmation.reason || confirmation.tool_name || confirmation.tool}</div>
      <div className="confirm-params">
        {confirmation.tool}
        {confirmation.params ? `\n${JSON.stringify(confirmation.params, null, 2)}` : ""}
      </div>
      <div className="row">
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
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [pendingConfirm, setPendingConfirm] = useState<any | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const scrollDown = useCallback(() => {
    requestAnimationFrame(() => {
      if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    });
  }, []);

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
    // open most recent conversation on mount
    if (!conversationId && conversations.length > 0 && messages.length === 0) {
      loadMessages(conversations[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setSending(true);

    const userMsg: ChatMsg = { id: `u-${Date.now()}`, role: "user", content: text };
    const aiMsg: ChatMsg = {
      id: `a-${Date.now()}`, role: "assistant", content: "", streaming: true,
      tools: [], memoriesUsed: [],
    };
    setMessages((m) => [...m, userMsg, aiMsg]);
    scrollDown();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChat(text, conversationId, (ev) => {
        if (ev.event === "meta") {
          aiMsg.mode = ev.mode;
          aiMsg.memoriesUsed = ev.memories_used || [];
          setMessages((m) => m.map((x) => (x.id === aiMsg.id ? { ...aiMsg } : x)));
        } else if (ev.event === "delta") {
          aiMsg.content += ev.text;
          setMessages((m) => m.map((x) => (x.id === aiMsg.id ? { ...aiMsg } : x)));
          scrollDown();
        } else if (ev.event === "tool_start") {
          aiMsg.tools = [...(aiMsg.tools || []), { tool: ev.tool, name: ev.name, state: "running" }];
          setMessages((m) => m.map((x) => (x.id === aiMsg.id ? { ...aiMsg } : x)));
          scrollDown();
        } else if (ev.event === "tool_end") {
          aiMsg.tools = (aiMsg.tools || []).map((t) =>
            t.tool === ev.tool && t.state === "running"
              ? { ...t, state: ev.success ? "ok" : "fail", summary: ev.summary }
              : t,
          );
          setMessages((m) => m.map((x) => (x.id === aiMsg.id ? { ...aiMsg } : x)));
        } else if (ev.event === "confirmation_required") {
          setPendingConfirm(ev);
          setMessages((m) => m.map((x) => (x.id === aiMsg.id ? { ...aiMsg } : x)));
        } else if (ev.event === "error") {
          aiMsg.content += (aiMsg.content ? "\n\n" : "") + `⚠️ ${ev.message}`;
          setMessages((m) => m.map((x) => (x.id === aiMsg.id ? { ...aiMsg } : x)));
        } else if (ev.event === "done") {
          aiMsg.streaming = false;
          if (ev.conversation_id) setConversationId(ev.conversation_id);
          setMessages((m) => m.map((x) => (x.id === aiMsg.id ? { ...aiMsg } : x)));
        }
      }, controller.signal);
    } catch (e: any) {
      aiMsg.streaming = false;
      aiMsg.content += (aiMsg.content ? "\n\n" : "") + `⚠️ ${e.message || "Connection lost."}`;
      setMessages((m) => m.map((x) => (x.id === aiMsg.id ? { ...aiMsg } : x)));
    } finally {
      setSending(false);
      abortRef.current = null;
      loadConversations();
      // check for any pending confirmations
      try {
        const r = await confirmationApi.pending();
        if (r.confirmations.length > 0) setPendingConfirm(r.confirmations[0]);
      } catch { /* ignore */ }
    }
  };

  const newConversation = () => {
    setMessages([]);
    setConversationId(null);
    setPendingConfirm(null);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <Layout title="Chat" subtitle="Converse, plan and execute — through the permission firewall" fullscreen>
      <div className="chat-page" style={{ height: "100%" }}>
        <div className="chat-scroll" ref={scrollRef}>
          {/* conversation switcher */}
          {conversations.length > 0 && (
            <div className="row wrap mb-14" style={{ justifyContent: "center" }}>
              <button className="btn secondary small" onClick={newConversation}>+ New</button>
              {conversations.slice(0, 8).map((c) => (
                <button
                  key={c.id}
                  className={`btn small ${c.id === conversationId ? "" : "secondary"}`}
                  onClick={() => loadMessages(c.id)}
                  style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                >
                  {c.title}
                </button>
              ))}
            </div>
          )}

          {/* honest mode banner */}
          {!aiConfigured && (
            <div className="mode-banner local" role="status">
              <span aria-hidden>💡</span>
              <div>
                <strong>Local Mode.</strong> No AI provider is configured on this deployment —
                free-form AI conversation is unavailable (we don't fake it). Real commands still
                work: tasks, calendar, memory, math, time, web search. Type <code>help</code> for examples.
              </div>
            </div>
          )}

          <div className="chat-stream">
            {messages.length === 0 && (
              <div className="empty" style={{ marginTop: 40 }}>
                <div className="big" aria-hidden>✦</div>
                <div style={{ fontWeight: 600, color: "var(--text-dim)" }}>
                  Hello {user?.display_name?.split(" ")[0]}, I'm MANISK.
                </div>
                <div className="small mt-8">
                  {aiConfigured
                    ? "Ask me anything, or ask me to plan and execute tasks for you."
                    : "Try: “create task Buy groceries due tomorrow 5pm” · “remember that I prefer tea” · “what is 12*(8+4)”"}
                </div>
              </div>
            )}

            {messages.map((m) => (
              <div key={m.id} className={`msg ${m.role}`}>
                <div className="msg-avatar" aria-hidden>
                  {m.role === "user" ? (user?.display_name?.[0] || "U") : "M"}
                </div>
                <div className="msg-body">
                  <div className="msg-meta">
                    {m.role === "user" ? "You" : "MANISK"}
                    {m.mode === "local" && <span className="mem-chip">local mode</span>}
                    {(m.memoriesUsed || []).slice(0, 3).map((mem: any) => (
                      <span key={mem.id} className="mem-chip" title={mem.content}>
                        🧠 {mem.kind}
                      </span>
                    ))}
                  </div>
                  <div className="msg-bubble">
                    {renderRichText(m.content)}
                    {m.streaming && m.content === "" && <Spinner />}
                  </div>
                  {(m.tools || []).map((t, i) => (
                    <div key={i} className={`tool-chip ${t.state === "ok" ? "ok" : t.state === "fail" ? "fail" : ""}`}>
                      {t.state === "running" ? <Spinner /> : t.state === "ok" ? "✓" : "✗"}
                      <span className="mono">{t.tool}</span>
                      {t.summary && <span style={{ color: "var(--text-dim)" }}>— {t.summary}</span>}
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {pendingConfirm && (
              <div className="msg assistant">
                <div className="msg-avatar" aria-hidden>M</div>
                <div className="msg-body">
                  <ConfirmationCard
                    confirmation={pendingConfirm}
                    onResolved={() => {
                      setPendingConfirm(null);
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
              placeholder={aiConfigured ? "Message MANISK… (Enter to send)" : "Try “help” — or “create task …” (Enter to send)"}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              disabled={sending}
              aria-label="Message"
            />
            <button className="send-btn" onClick={send} disabled={sending || !input.trim()} aria-label="Send">
              {sending ? <Spinner /> : "➤"}
            </button>
          </div>
        </div>
      </div>
    </Layout>
  );
}
