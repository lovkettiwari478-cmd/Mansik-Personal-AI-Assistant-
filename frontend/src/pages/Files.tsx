/* Files page — private storage with upload/download/delete. */

import { useCallback, useEffect, useRef, useState } from "react";
import { fmtBytes, fmtDate, fileApi } from "../api";
import { useToast } from "../state";
import { Badge, EmptyState, Loading } from "../components/ui";
import Layout from "../components/Layout";

export default function FilesPage() {
  const { push } = useToast();
  const [files, setFiles] = useState<any[]>([]);
  const [totalBytes, setTotalBytes] = useState(0);
  const [maxBytes, setMaxBytes] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const r = await fileApi.list();
      setFiles(r.files);
      setTotalBytes(r.total_bytes);
      setMaxBytes(r.max_bytes);
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [push]);

  useEffect(() => { load(); }, [load]);

  const upload = async (f: File) => {
    setUploading(true);
    try {
      await fileApi.upload(f);
      push(`${f.name} uploaded`, "success");
      load();
    } catch (e: any) {
      push(e.message, "error");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const remove = async (id: string, name: string) => {
    if (!confirm(`Delete ${name} permanently?`)) return;
    try {
      await fileApi.remove(id);
      push("File deleted", "success");
      load();
    } catch (e: any) { push(e.message, "error"); }
  };

  return (
    <Layout title="Files" subtitle="Your private storage — isolated, validated, size-limited">
      <div className="row between mb-14">
        <button className="btn small" disabled={uploading} onClick={() => inputRef.current?.click()}>
          {uploading ? "Uploading…" : "⬆ Upload file"}
        </button>
        <span className="small faint">
          {fmtBytes(totalBytes)} used · max {fmtBytes(maxBytes)} per file · .txt .md .json .csv .pdf .png .jpg …
        </span>
        <input
          ref={inputRef} type="file" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); }}
        />
      </div>

      {loading ? <Loading /> : files.length === 0 ? (
        <EmptyState icon="📁" title="No files" hint="Upload documents — MANISK can list and read them (with your permission)." />
      ) : (
        files.map((f) => (
          <div key={f.id} className="list-item">
            <div className="grow">
              <div style={{ fontWeight: 600 }}>{f.filename}</div>
              <div className="small faint">
                {fmtBytes(f.size_bytes)} · {f.mime_type} · {fmtDate(f.created_at)}
              </div>
            </div>
            {f.has_text && <Badge kind="info">text extracted</Badge>}
            <a className="btn secondary small" href={`/api/files/${f.id}/download`}>Download</a>
            <button className="btn ghost small" onClick={() => remove(f.id, f.filename)} aria-label="Delete">🗑</button>
          </div>
        ))
      )}
    </Layout>
  );
}
