import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { UploadCloud, FolderOpen, Files, X, Trash2, CheckCircle, AlertTriangle, RefreshCw } from "lucide-react";

const ALLOWED = new Set([".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".shp.xml", ".csv", ".xlsx", ".xls", ".json", ".geojson"]);
const ONE_GIB = 1024 * 1024 * 1024;
const QUOTA = 5 * ONE_GIB;

const authH = () => ({ Authorization: "Bearer " + localStorage.getItem("token") });

const fmtBytes = (n) => {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(v >= 100 || i === 0 ? 0 : 1) + " " + u[i];
};

// Strip the picked root folder: webkitRelativePath "Batch/req1/a.shp"
// must land as "req1/a.shp" so each request folder stays top-level.
const serverRel = (f) => {
  const w = f.webkitRelativePath || f.name || "";
  const parts = w.split("/").filter(Boolean);
  if (parts.length > 1) {
    const rel = parts.slice(1).join("/");
    if (rel) return rel;
  }
  return f.name || "file";
};

function analyzePicked(files) {
  const errors = [];
  const warnings = [];
  let total = 0;
  const sets = new Map();
  for (const f of files) {
    total += f.size || 0;
    const rel = serverRel(f);
    const name = rel.split("/").pop();
    const lower = name.toLowerCase();
    if (lower.endsWith(".zip")) {
      errors.push(`"${name}" is a zip — extract it on your PC before uploading.`);
      continue;
    }
    let ext = "";
    const dot = name.lastIndexOf(".");
    if (lower.endsWith(".shp.xml")) ext = ".shp.xml";
    else if (dot >= 0) ext = name.slice(dot).toLowerCase();
    if (!ALLOWED.has(ext)) {
      errors.push(`"${name}" has unsupported type (${ext || "no extension"}).`);
      continue;
    }
    const base = (lower.endsWith(".shp.xml") ? name.slice(0, -8) : dot >= 0 ? name.slice(0, dot) : name).toLowerCase();
    const dir = rel.split("/").slice(0, -1).join("/");
    const key = dir + "\n" + base;
    if (!sets.has(key)) sets.set(key, new Set());
    sets.get(key).add(ext);
    if ((f.size || 0) > ONE_GIB) errors.push(`"${name}" exceeds the 1 GiB per-file limit.`);
  }
  if (total > QUOTA) errors.push("Selection exceeds the 5 GiB session quota — split it into smaller batches.");
  let shpCount = 0;
  for (const [key, exts] of sets) {
    if (!exts.has(".shp")) continue;
    shpCount++;
    const base = key.split("\n")[1];
    const missing = [".shx", ".dbf"].filter((e) => !exts.has(e));
    if (missing.length) errors.push(`"${base}" is missing ${missing.join(" + ")} — a shapefile needs .shp + .shx + .dbf.`);
    else if (!exts.has(".prj")) warnings.push(`"${base}" has no .prj — the coordinate system may be guessed.`);
  }
  return { errors, warnings, total, shpCount, count: files.length };
}

/**
 * Upload input folders from the browser into a server staging session.
 * onStaged({ inputDir, outputGpkg, doneDir, conflictsFile }) fires when the
 * upload completes; onCleared() fires when the staging session is deleted.
 */
export default function StagingUpload({ onStaged, onCleared, disabled }) {
  const [files, setFiles] = useState([]);
  const [session, setSession] = useState(null);
  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState({ done: 0, total: 0, current: "" });
  const dirRef = useRef(null);
  const filesRef = useRef(null);
  const loadedRef = useRef(0);

  useEffect(() => {
    if (dirRef.current) dirRef.current.setAttribute("webkitdirectory", "");
  }, []);

  const analysis = useMemo(() => analyzePicked(files), [files]);

  const pick = (list) => {
    setError("");
    setSummary(null);
    setSession(null);
    setFiles(Array.from(list || []));
  };

  const startUpload = async () => {
    if (analysis.errors.length || !files.length || busy) return;
    setBusy(true);
    setError("");
    loadedRef.current = 0;
    setProgress({ done: 0, total: analysis.total, current: "" });
    try {
      const init = await axios.post("/api/v1/staging/init", {}, { headers: authH() });
      const sid = init.data.session_id;
      setSession(sid);
      let done = 0;
      for (const f of files) {
        setProgress((p) => ({ ...p, current: f.name }));
        const fd = new FormData();
        fd.append("session_id", sid);
        fd.append("relative_path", serverRel(f));
        fd.append("file", f);
        await axios.post("/api/v1/staging/upload", fd, {
          headers: { ...authH(), "Content-Type": "multipart/form-data" },
          onUploadProgress: (e) => {
            const base = done;
            const loaded = e.loaded || 0;
            setProgress((p) => ({ ...p, done: Math.min(base + loaded, p.total || base + loaded) }));
          },
        });
        done += f.size || 0;
        loadedRef.current = done;
        setProgress((p) => ({ ...p, done }));
      }
      const list = await axios.get("/api/v1/staging/list", { params: { session_id: sid }, headers: authH() });
      setSummary(list.data);
      setProgress((p) => ({ ...p, current: "", done: p.total }));
      onStaged && onStaged({
        inputDir: init.data.input_dir,
        outputGpkg: init.data.output_gpkg,
        doneDir: init.data.done_dir,
        conflictsFile: init.data.conflicts_file,
      });
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message || "Upload failed";
      setError(typeof msg === "string" ? msg : "Upload failed");
      if (session) {
        try { await axios.delete("/api/v1/staging/session", { params: { session_id: session }, headers: authH() }); } catch (e2) { /* ignore */ }
        setSession(null);
      }
    } finally {
      setBusy(false);
    }
  };

  const clearAll = async () => {
    if (session) {
      try { await axios.delete("/api/v1/staging/session", { params: { session_id: session }, headers: authH() }); } catch (e) { /* ignore */ }
    }
    setFiles([]);
    setSession(null);
    setSummary(null);
    setError("");
    setProgress({ done: 0, total: 0, current: "" });
    onCleared && onCleared();
  };

  const pct = progress.total > 0 ? Math.min(100, Math.round((progress.done / progress.total) * 100)) : 0;

  return (
    <div className="space-y-3">
      <input ref={dirRef} type="file" multiple className="hidden" onChange={(e) => pick(e.target.files)} disabled={disabled || busy} />
      <input ref={filesRef} type="file" multiple className="hidden" onChange={(e) => pick(e.target.files)} disabled={disabled || busy} />
      <div className="flex gap-2">
        <button
          onClick={() => dirRef.current && dirRef.current.click()}
          disabled={disabled || busy}
          className="flex-1 inline-flex items-center justify-center px-3 py-2 rounded-md text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition"
        >
          <FolderOpen className="w-4 h-4 mr-1.5" /> Choose folder
        </button>
        <button
          onClick={() => filesRef.current && filesRef.current.click()}
          disabled={disabled || busy}
          title="Pick individual files instead of a folder"
          className="flex-1 inline-flex items-center justify-center px-3 py-2 rounded-md text-xs font-semibold bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition"
        >
          <Files className="w-4 h-4 mr-1.5" /> Choose files
        </button>
      </div>
      <p className="text-[11px] text-gray-400 leading-snug">
        Select the folder that <span className="font-semibold text-gray-500">contains</span> the request folders
        (each with its .shp + .shx + .dbf). Files upload to the server; the pipeline runs there.
      </p>

      {files.length > 0 && (
        <div className="border border-gray-200 rounded-md p-2.5 bg-gray-50 text-xs">
          <div className="flex items-center justify-between mb-1">
            <span className="font-semibold text-gray-700">{files.length} file(s) · {fmtBytes(analysis.total)} · {analysis.shpCount} shapefile(s)</span>
            {!busy && (
              <button onClick={() => pick([])} className="text-gray-400 hover:text-gray-600" title="Clear selection">
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <ul className="max-h-24 overflow-y-auto space-y-0.5 text-gray-500">
            {files.slice(0, 8).map((f, i) => (
              <li key={i} className="truncate font-mono text-[11px]">{serverRel(f)} · {fmtBytes(f.size)}</li>
            ))}
            {files.length > 8 && <li className="text-gray-400">…and {files.length - 8} more</li>}
          </ul>
        </div>
      )}

      {analysis.errors.length > 0 && (
        <div className="border border-red-200 bg-red-50 rounded-md p-2.5 text-xs text-red-700 space-y-1">
          {analysis.errors.slice(0, 6).map((m, i) => <p key={i}>• {m}</p>)}
          {analysis.errors.length > 6 && <p>…and {analysis.errors.length - 6} more</p>}
        </div>
      )}
      {analysis.warnings.length > 0 && (
        <div className="border border-amber-200 bg-amber-50 rounded-md p-2.5 text-xs text-amber-700 space-y-1">
          {analysis.warnings.slice(0, 4).map((m, i) => <p key={i}>• {m}</p>)}
          {analysis.warnings.length > 4 && <p>…and {analysis.warnings.length - 4} more</p>}
        </div>
      )}

      {busy && (
        <div>
          <div className="h-2 rounded-full bg-gray-200 overflow-hidden">
            <div className="h-full bg-blue-600 transition-all" style={{ width: pct + "%" }} />
          </div>
          <p className="text-[11px] text-gray-500 mt-1 truncate">
            Uploading {pct}% · {fmtBytes(progress.done)} of {fmtBytes(progress.total)}
            {progress.current ? ` · ${progress.current}` : ""}
          </p>
        </div>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}

      {summary ? (
        <div className="border border-emerald-200 bg-emerald-50 rounded-md p-2.5 text-xs text-emerald-800">
          <p className="font-semibold flex items-center">
            <CheckCircle className="w-4 h-4 mr-1" />
            Uploaded {summary.file_count} file(s) · {fmtBytes(summary.total_bytes)}
          </p>
          <button onClick={clearAll} disabled={busy} className="mt-1.5 inline-flex items-center text-red-600 hover:text-red-700 font-medium disabled:opacity-50">
            <Trash2 className="w-3.5 h-3.5 mr-1" /> Clear staging
          </button>
        </div>
      ) : (
        <button
          onClick={startUpload}
          disabled={disabled || busy || !files.length || analysis.errors.length > 0}
          title={analysis.errors.length ? "Fix the problems above first" : "Upload to the server"}
          className="w-full inline-flex items-center justify-center px-3 py-2 rounded-md text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition"
        >
          {busy ? <RefreshCw className="w-4 h-4 mr-1.5 animate-spin" /> : <UploadCloud className="w-4 h-4 mr-1.5" />}
          {busy ? "Uploading..." : "Upload to server"}
        </button>
      )}
    </div>
  );
}
