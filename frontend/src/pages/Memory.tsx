/* Memory v2 — premium memory management with clear separation of
 * conversation history / saved memory / temporary context. */

import { useCallback, useEffect, useState } from "react";
import { fmtDate, memoryApi, settingsApi } from "../api";
import { useToast } from "../state";
import { EmptyState, Field, Loading, Modal, Toggle } from "../components/ui";
import Layout from "../components/Layout";

const KINDS = ["all", "fact", "preference", "person", "project", "goal", "event"];
const KIND_ICON: Record<string, string> = {
  fact: "◆", preference: "✦", person: "◉", project: "◈", goal: "★", event: "▤",
};

export default function MemoryPage() {
  const { push } = useToast();
  const [memories, setMemories] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [kindFilter, setKindFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[] | null>(null);
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState({ content: "", kind: "fact", importance: 50 });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [m, s] = await Promise.all([memoryApi.list(), settingsApi.get()]);
      setMemories(m.memories);
      setMemoryEnabled(s.memory_enabled);
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [push]);

  useEffect(() => { load(); }, [load]);

  const search = async () => {
    if (!query.trim()) { setSearchResults(null); return; }
    try {
      const r = await memoryApi.search(query);
      setSearchResults(r.memories);
    } catch (e: any) { push(e.message, "error"); }
  };

  const save = async () => {
    setBusy(true);
    try {
      if (editing) {
        await memoryApi.update(editing.id, form);
        push("Memory updated", "success");
      } else {
        await memoryApi.create(form);
        push("Memory stored", "success");
      }
      setModal(false);
      setEditing(null);
      setForm({ content: "", kind: "fact", importance: 50 });
      load();
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!confirm("Delete this memory permanently?")) return;
    try {
      await memoryApi.remove(id);
      push("Memory deleted", "success");
      load();
    } catch (e: any) { push(e.message, "error"); }
  };

  const toggleMemory = async (v: boolean) => {
    setMemoryEnabled(v);
    try {
      await settingsApi.patch({ memory_enabled: v });
      push(v ? "Memory enabled" : "Memory disabled — retrieval & storage stopped", "success");
    } catch (e: any) {
      setMemoryEnabled(!v);
      push(e.message, "error");
    }
  };

  const shown = (searchResults ?? memories)
    .filter((m) => kindFilter === "all" || m.kind === kindFilter);

  return (
    <Layout title="Memory" subtitle="Everything MANISK remembers about you — visible, editable, deletable">
      {/* master switch + explanation */}
      <div className="card mb-14">
        <div className="row between">
          <div className="grow">
            <div className="card-title">Long-term memory</div>
            <div className="small muted">
              When off, MANISK stops retrieving and storing memories entirely.
            </div>
          </div>
          <Toggle on={memoryEnabled} onChange={toggleMemory} label="Long-term memory" />
        </div>
      </div>

      {/* memory model explainer */}
      <div className="card mb-14">
        <div className="card-title">How MANISK's memory works</div>
        <div className="grid cols-3" style={{ gap: 10 }}>
          <div className="stat" style={{ padding: "12px 14px" }}>
            <div className="stat-label">💬 Conversation history</div>
            <div className="small muted mt-8">
              Your chat messages, per conversation. Delete any conversation in Chat.
            </div>
          </div>
          <div className="stat" style={{ padding: "12px 14px", borderColor: "rgba(109,124,255,0.35)" }}>
            <div className="stat-label" style={{ color: "#aab4ff" }}>◉ Saved memory</div>
            <div className="small muted mt-8">
              Durable facts you asked MANISK to remember — shown on this page, fully editable.
            </div>
          </div>
          <div className="stat" style={{ padding: "12px 14px" }}>
            <div className="stat-label">◌ Temporary context</div>
            <div className="small muted mt-8">
              Working context for the current turn (open tasks, time). Never persisted.
            </div>
          </div>
        </div>
      </div>

      {/* toolbar */}
      <div className="row wrap mb-14">
        <input
          className="input grow" style={{ maxWidth: 380 }}
          placeholder="Search memories (full-text)…" value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") search(); }}
        />
        <button className="btn small" onClick={search}>Search</button>
        {searchResults && (
          <button className="btn secondary small" onClick={() => { setSearchResults(null); setQuery(""); }}>
            Clear ({searchResults.length})
          </button>
        )}
        <button className="btn secondary small" onClick={() => { setEditing(null); setModal(true); }}>＋ Add memory</button>
      </div>
      <div className="seg mb-14">
        {KINDS.map((k) => (
          <button key={k} className={`seg-btn ${kindFilter === k ? "active" : ""}`}
                  onClick={() => setKindFilter(k)}>
            {k === "all" ? "All" : `${KIND_ICON[k] || "◆"} ${k}`}
          </button>
        ))}
      </div>

      {loading ? <Loading /> : shown.length === 0 ? (
        <EmptyState
          icon="◉"
          title={searchResults ? "No matching memories" : kindFilter === "all" ? "No memories yet" : `No ${kindFilter} memories`}
          hint={'Ask MANISK: “remember that my sister’s birthday is May 12”'}
        />
      ) : shown.map((m) => (
        <div key={m.id} className="list-item">
          <div className="grow">
            <div>{m.content}</div>
            <div className="small faint mt-8">
              {KIND_ICON[m.kind] || "◆"} {m.kind} · importance {m.importance} · {m.source} · created {fmtDate(m.created_at)}
            </div>
          </div>
          <button className="btn ghost small" aria-label="Edit"
                  onClick={() => {
                    setEditing(m);
                    setForm({ content: m.content, kind: m.kind, importance: m.importance });
                    setModal(true);
                  }}>
            ✎
          </button>
          <button className="btn ghost small" onClick={() => remove(m.id)} aria-label="Delete">🗑</button>
        </div>
      ))}

      {modal && (
        <Modal title={editing ? "Edit memory" : "Add memory"} onClose={() => { setModal(false); setEditing(null); }}>
          <Field label="Content">
            <textarea className="textarea" value={form.content} maxLength={2000} autoFocus
                      onChange={(e) => setForm({ ...form, content: e.target.value })} />
          </Field>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Field label="Kind">
              <select className="select" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                {KINDS.slice(1).map((k) => <option key={k}>{k}</option>)}
              </select>
            </Field>
            <Field label={`Importance: ${form.importance}`}>
              <input type="range" min={0} max={100} value={form.importance}
                     onChange={(e) => setForm({ ...form, importance: Number(e.target.value) })}
                     style={{ marginTop: 12 }} />
            </Field>
          </div>
          <button className="btn" style={{ width: "100%" }} disabled={busy || form.content.trim().length < 3} onClick={save}>
            {editing ? "Save changes" : "Store memory"}
          </button>
        </Modal>
      )}
    </Layout>
  );
}
