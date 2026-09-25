/* Memory page — full user control over long-term memory. */

import { useCallback, useEffect, useState } from "react";
import { fmtDate, memoryApi, settingsApi } from "../api";
import { useToast } from "../state";
import { Badge, EmptyState, Field, Loading, Modal, Toggle } from "../components/ui";
import Layout from "../components/Layout";

const KINDS = ["fact", "preference", "person", "project", "goal", "event"];

export default function MemoryPage() {
  const { push } = useToast();
  const [memories, setMemories] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [memoryEnabled, setMemoryEnabled] = useState(true);
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
      push(v ? "Memory enabled" : "Memory disabled — MANISK will stop retrieving & storing", "success");
    } catch (e: any) {
      setMemoryEnabled(!v);
      push(e.message, "error");
    }
  };

  const shown = searchResults ?? memories;

  return (
    <Layout title="Memory" subtitle="Everything MANISK remembers about you — visible, editable, deletable">
      <div className="card mb-14">
        <Toggle
          on={memoryEnabled}
          onChange={toggleMemory}
          label="Long-term memory"
          description="When off, MANISK stops retrieving and storing memories entirely."
        />
      </div>

      <div className="row wrap mb-14">
        <input
          className="input grow" style={{ maxWidth: 420 }}
          placeholder="Search memories…" value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") search(); }}
        />
        <button className="btn small" onClick={search}>Search</button>
        {searchResults && (
          <button className="btn secondary small" onClick={() => { setSearchResults(null); setQuery(""); }}>
            Clear ({searchResults.length} results)
          </button>
        )}
        <button className="btn secondary small" onClick={() => { setEditing(null); setModal(true); }}>+ Add memory</button>
      </div>

      {loading ? <Loading /> : shown.length === 0 ? (
        <EmptyState
          icon="🧠" title={searchResults ? "No matching memories" : "No memories yet"}
          hint={"Ask MANISK: “remember that my sister’s birthday is May 12”"}
        />
      ) : (
        shown.map((m) => (
          <div key={m.id} className="list-item">
            <div className="grow">
              <div>{m.content}</div>
              <div className="small faint mt-8">
                {fmtDate(m.created_at)} · importance {m.importance} · {m.source}
              </div>
            </div>
            <Badge kind="accent">{m.kind}</Badge>
            <button className="btn ghost small" aria-label="Edit"
                    onClick={() => { setEditing(m); setForm({ content: m.content, kind: m.kind, importance: m.importance }); setModal(true); }}>
              ✎
            </button>
            <button className="btn ghost small" onClick={() => remove(m.id)} aria-label="Delete">🗑</button>
          </div>
        ))
      )}

      {modal && (
        <Modal title={editing ? "Edit memory" : "Add memory"} onClose={() => { setModal(false); setEditing(null); }}>
          <Field label="Content">
            <textarea className="textarea" value={form.content} maxLength={2000}
                      onChange={(e) => setForm({ ...form, content: e.target.value })} />
          </Field>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Field label="Kind">
              <select className="select" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                {KINDS.map((k) => <option key={k}>{k}</option>)}
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
