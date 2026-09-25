import React, { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import {
  DatabaseZap, UploadCloud, RefreshCcw, ExternalLink, Undo2, History,
  AlertTriangle, CheckCircle2, Loader2, Search, ArrowRight, X
} from "lucide-react";

const authHeaders = () => ({ Authorization: "Bearer " + localStorage.getItem("token") });
const API = "/api/v1/update";
const MODE_OPTIONS = [["update_in_place", "Update in place"], ["delete_and_insert", "Delete & insert"]];

function ResizeHandle({ width, min, max, onWidth }) {
  const start = useRef(null);
  const onPointerDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    start.current = { x: e.clientX, w: width };
    const move = (ev) => {
      if (!start.current) return;
      const dx = ev.clientX - start.current.x;
      onWidth(Math.max(min, Math.min(max, start.current.w - dx)));
    };
    const up = () => {
      start.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <div
      onPointerDown={onPointerDown}
      className="absolute left-0 inset-y-0 w-1.5 cursor-ew-resize select-none flex items-center justify-center group"
      style={{ touchAction: "none" }}
      title="Drag to resize"
    >
      <div className="w-[3px] h-10 rounded-full bg-gray-300/70 group-hover:bg-blue-500 transition-colors" />
    </div>
  );
}

export default function UpdateGeometryPanel({ me, onClose, panelWidth = 460, onPanelWidth = () => {} }) {
  const isEditor = !!(me && (me.role === "admin" || me.role === "editor" || (me.permissions || []).includes("edit_geometry")));

  const [config, setConfig] = useState(null);
  const [configErr, setConfigErr] = useState("");
  const [keyColumn, setKeyColumn] = useState("Req_Number");
  const [keyValue, setKeyValue] = useState("");

  const [querying, setQuerying] = useState(false);
  const [queryErr, setQueryErr] = useState("");
  const [matches, setMatches] = useState(null);

  const [staging, setStaging] = useState(null);
  const [stagingErr, setStagingErr] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadName, setUploadName] = useState("");
  const fileRef = useRef(null);

  const [mapping, setMapping] = useState([]);
  const [modes, setModes] = useState({});
  const [persistClass, setPersistClass] = useState({});
  const [proceedMissing, setProceedMissing] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewErr, setPreviewErr] = useState("");
  const [previewing, setPreviewing] = useState(false);

  const [committing, setCommitting] = useState(false);
  const [commitResult, setCommitResult] = useState(null);
  const [commitErr, setCommitErr] = useState("");
  const [archiveRows, setArchiveRows] = useState([]);

  const [history, setHistory] = useState(null);
  const [historyErr, setHistoryErr] = useState("");
  const [undoing, setUndoing] = useState(null);
  const [undoNote, setUndoNote] = useState(null);
  const [showHistory, setShowHistory] = useState(false);

  const layerLabel = useCallback((t) => {
    if (!config || !config.layers) return t;
    const l = config.layers.find((x) => x.table === t);
    return l ? l.label : t;
  }, [config]);

  const loadConfig = useCallback(async () => {
    try {
      const r = await axios.get(API + "/config", { headers: authHeaders() });
      setConfig(r.data);
      setConfigErr("");
      if (r.data.key_column) setKeyColumn(r.data.key_column);
    } catch (e) {
      setConfigErr(e && e.response && e.response.data && e.response.data.detail || (e && e.message) || "Failed to load config");
    }
  }, []);

  useEffect(() => { if (isEditor) loadConfig(); }, [isEditor, loadConfig]);

  const refreshMatches = async (value) => {
    try {
      const r = await axios.post(API + "/query", { key_column: keyColumn, value: value.trim() }, { headers: authHeaders() });
      setMatches(r.data);
    } catch (_e) { /* ignore refresh failures */ }
  };

  const runQuery = async () => {
    if (!keyValue.trim()) return;
    setQuerying(true); setQueryErr(""); setMatches(null);
    try {
      const r = await axios.post(API + "/query", { key_column: keyColumn, value: keyValue.trim() }, { headers: authHeaders() });
      setMatches(r.data);
    } catch (e) {
      setQueryErr(e && e.response && e.response.data && e.response.data.detail || (e && e.message) || "Query failed");
    } finally { setQuerying(false); }
  };

  const fetchHistoryData = async () => {
    const r = await axios.get(API + "/history", { headers: authHeaders() });
    return r.data;
  };

  const loadHistory = useCallback(async () => {
    setHistoryErr("");
    try {
      setHistory(await fetchHistoryData());
    } catch (e) {
      setHistoryErr(e && e.response && e.response.data && e.response.data.detail || (e && e.message) || "Failed to load history");
    }
  }, []);

  const handleUpload = async (evt) => {
    const file = evt.target.files && evt.target.files[0];
    if (!file) return;
    setUploading(true); setStagingErr(""); setUploadName(file.name);
    setStaging(null); setMapping([]); setPreview(null); setPreviewErr("");
    setCommitResult(null); setArchiveRows([]); setModes({}); setPersistClass({}); setProceedMissing(false);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await axios.post(API + "/upload", fd, { headers: authHeaders(), params: { key_column: keyColumn } });
      const d = r.data;
      setStaging(d);
      setMapping((d.files || []).map((f) => ({ file_base: f.file_base, layer_table: f.detected_layer || "" })));
    } catch (e) {
      setStagingErr(e && e.response && e.response.data && e.response.data.detail || (e && e.message) || "Upload failed");
    } finally { setUploading(false); }
  };

  const changeMapping = (i, layer_table) => setMapping((m) => m.map((x, j) => (j === i ? { ...x, layer_table } : x)));

  const buildPayload = () => ({
    staging_id: staging ? staging.staging_id : "",
    key_column: keyColumn,
    key_value: keyValue.trim(),
    mapping: mapping.filter((m) => m.layer_table).map((m) => ({ file_base: m.file_base, layer_table: m.layer_table })),
    modes,
    persist_classification: persistClass,
  });

  const runPreview = async () => {
    if (!keyValue.trim() || !mapping.some((m) => m.layer_table)) return;
    setPreviewing(true); setPreviewErr(""); setPreview(null);
    setCommitResult(null); setArchiveRows([]); setProceedMissing(false);
    try {
      const r = await axios.post(API + "/preview", buildPayload(), { headers: authHeaders() });
      setPreview(r.data);
    } catch (e) {
      setPreviewErr(e && e.response && e.response.data && e.response.data.detail || (e && e.message) || "Preview failed");
    } finally { setPreviewing(false); }
  };

  const runCommit = async () => {
    setCommitting(true); setCommitErr(""); setCommitResult(null);
    try {
      const payload = buildPayload();
      if (proceedMissing) payload.proceed_unresolved = true;
      const r = await axios.post(API + "/commit", payload, { headers: authHeaders() });
      const d = r.data;
      setCommitResult(d);
      let items = [];
      try {
        const h = await fetchHistoryData();
        setHistory(h);
        items = (h.items || []).filter((x) => x.key_value === keyValue.trim() && !x.undone_at);
      } catch (e) {
        setHistoryErr(e && e.response && e.response.data && e.response.data.detail || (e && e.message) || "Failed to load history");
      }
      setArchiveRows((d.summary || []).map((s) => {
        const arc = items.find((x) => x.layer_table === s.layer_table);
        return { ...s, archive_id: arc ? arc.id : null };
      }));
      setPreview(null);
      await refreshMatches(keyValue);
    } catch (e) {
      setCommitErr(e && e.response && e.response.data && e.response.data.detail || (e && e.message) || "Commit failed");
    } finally { setCommitting(false); }
  };

  const runUndo = async (archiveId) => {
    setUndoing(archiveId); setUndoNote(null);
    try {
      const r = await axios.post(API + "/undo?archive_id=" + encodeURIComponent(archiveId), {}, { headers: authHeaders() });
      setUndoNote(r.data);
      try {
        setHistory(await fetchHistoryData());
      } catch (_e) { /* ignore */ }
      setArchiveRows((rows) => rows.filter((x) => x.archive_id !== archiveId));
      if (keyValue.trim()) await refreshMatches(keyValue);
    } catch (e) {
      setUndoNote(null);
      setHistoryErr(e && e.response && e.response.data && e.response.data.detail || (e && e.message) || "Undo failed");
    } finally { setUndoing(null); }
  };

  const modeOf = (layerTable) => modes[layerTable] || (config && config.classifications && config.classifications[layerTable] && config.classifications[layerTable].update_mode) || "";
  const setMode = (layerTable, mode) => {
    setModes((mm) => (mode ? { ...mm, [layerTable]: mode } : Object.fromEntries(Object.entries(mm).filter(([k]) => k !== layerTable))));
    if (persistClass[layerTable]) setPersistClass((pp) => ({ ...pp, [layerTable]: mode }));
  };
  const togglePersist = (layerTable, checked) => {
    setPersistClass((pp) => {
      const next = { ...pp };
      if (checked) next[layerTable] = modeOf(layerTable);
      else delete next[layerTable];
      return next;
    });
  };

  // Unresolved layers that still need a mode chosen: once every unclassified
  // layer has a mode picked (or comes from config), none block commit.
  const pendingUnresolved = (preview && preview.unresolved || []).filter((t) => !modeOf(t));

  if (!isEditor) return null;

  const matchLayers = matches ? matches.layers || [] : [];
  const matchCount = matchLayers.length;
  const planRows = preview ? (preview.plan || preview.layers || []) : [];
  const summaryRows = commitResult ? (commitResult.summary || []) : [];
  const sevClass = (sev) => sev === "red" ? "bg-red-100 text-red-700" : sev === "yellow" ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700";

  return (
    <div className="absolute top-[100px] right-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200 flex flex-col max-h-[calc(100vh-140px)]"
      style={{ width: panelWidth }}>
      <ResizeHandle width={panelWidth} min={380} max={640} onWidth={onPanelWidth} />
      <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100 flex-shrink-0">
        <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider flex items-center gap-1.5">
          <DatabaseZap className="w-3.5 h-3.5 text-blue-600" /> Update Geometry
        </h3>
        <div className="flex items-center gap-1">
          <button onClick={() => { setShowHistory((s) => !s); if (!showHistory) loadHistory(); }} title="Update History"
            className="p-1 text-gray-400 hover:text-gray-700"><History className="w-4 h-4" /></button>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700"><X className="w-4 h-4" /></button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {configErr && <p className="text-[11px] text-red-600">{configErr}</p>}
        {!config && !configErr && (
          <p className="text-[11px] text-gray-500 flex items-center gap-1.5">
            <Loader2 className="w-3 h-3 animate-spin text-blue-600" /> Loading configuration...
          </p>
        )}

        <div className="border border-gray-200 rounded-lg p-3 space-y-2">
          <p className="text-[11px] font-bold text-gray-600 flex items-center gap-1">
            <Search className="w-3 h-3 text-blue-600" /> 1. Query request number
          </p>
          <div className="flex gap-1.5">
            <input value={keyValue} onChange={(e) => setKeyValue(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runQuery()}
              placeholder={"Enter " + (keyColumn || "request number") + "..."}
              className="flex-1 border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
            <button onClick={runQuery} disabled={querying || !keyValue.trim()}
              className="px-3 py-1.5 rounded-md text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1">
              {querying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />} Query
            </button>
          </div>
          {queryErr && <p className="text-[11px] text-red-600">{queryErr}</p>}
        </div>

        {!querying && matches && (
          <div className="border border-gray-200 rounded-lg p-3 space-y-1.5">
            <p className="text-[11px] font-bold text-gray-600 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3 text-emerald-500" /> Matches for "{keyValue}"
            </p>
            {matchCount > 0 ? matchLayers.map((l, i) => (
              <div key={i} className="flex items-center justify-between text-xs rounded-md bg-gray-50 px-2 py-1.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-semibold text-gray-700 truncate">{layerLabel(l.table)}</span>
                  <span className="text-[10px] text-gray-400 font-semibold uppercase bg-white border border-gray-200 rounded-full px-1.5 py-0.5 flex-shrink-0">
                    {l.group ? l.group.role : "unclassified"}
                  </span>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {l.cardinality_violation && (
                    <span title={(l.cardinality_violation.message || "") + " (expected " + l.cardinality_violation.expected + ", found " + l.cardinality_violation.found + ")"}>
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                    </span>
                  )}
                  <span className={"text-[10px] font-semibold rounded-full px-1.5 py-0.5 " + (l.cardinality_violation ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700")}>
                    {l.count} feat
                  </span>
                </div>
              </div>
            )) : (
              <p className="text-[11px] text-amber-600">No matching records found for "{keyValue}".</p>
            )}
          </div>
        )}

        <div className="border border-gray-200 rounded-lg p-3 space-y-2">
          <p className="text-[11px] font-bold text-gray-600 flex items-center gap-1">
            <UploadCloud className="w-3 h-3 text-blue-600" /> 2. Upload edited shapefiles (ZIP)
          </p>
          <input ref={fileRef} type="file" accept=".zip,application/zip" className="hidden" onChange={handleUpload} />
          <button onClick={() => fileRef.current && fileRef.current.click()} disabled={uploading}
            className="w-full px-3 py-2.5 rounded-md text-xs font-semibold bg-white border-2 border-dashed border-blue-300 text-blue-600 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
            {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <UploadCloud className="w-4 h-4" />}
            {uploading ? "Uploading & unzipping..." : "Choose ZIP of shapefiles"}
          </button>
          {uploadName && !staging && <p className="text-[11px] text-gray-400 truncate">File: {uploadName}</p>}
          {stagingErr && <p className="text-[11px] text-red-600">{stagingErr}</p>}
        </div>

        {staging && !preview && !commitResult && (
          <div className="border border-gray-200 rounded-lg p-3 space-y-2">
            <p className="text-[11px] font-bold text-gray-600 flex items-center gap-1">
              <ArrowRight className="w-3 h-3 text-blue-600" /> 3. Confirm file → layer mapping
            </p>
            <p className="text-[11px] text-gray-400">Session: <span className="font-mono font-semibold text-gray-600">{staging.staging_id}</span></p>
            {(staging.files || []).map((f, i) => {
              const m = mapping[i] || {};
              return (
                <div key={i} className="space-y-1">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="font-semibold text-gray-700 flex-1 truncate">{f.file_base}</span>
                    <span className="text-[10px] text-gray-400">{f.gtype} · {f.count} feat</span>
                    {f.in_lineage && (
                      <span className="text-[10px] font-semibold text-blue-700 bg-blue-50 border border-blue-200 rounded-full px-1.5 py-0.5">in group</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <ArrowRight className="w-3 h-3 text-gray-300 flex-shrink-0" />
                    <select value={m.layer_table || ""} onChange={(e) => changeMapping(i, e.target.value)}
                      className="flex-1 border border-gray-300 rounded text-xs px-1.5 py-1">
                      <option value="">-- choose layer --</option>
                      {config && config.layers && config.layers.map((l) => (
                        <option key={l.table} value={l.table}>{l.label} ({l.table})</option>
                      ))}
                    </select>
                  </div>
                  {f.detected_layer && m.layer_table !== f.detected_layer && (
                    <p className="text-[10px] text-amber-600">Auto-detected: {layerLabel(f.detected_layer)}</p>
                  )}
                  {f.crs_note && <p className="text-[10px] text-amber-600">{f.crs_note}</p>}
                </div>
              );
            })}
            <button onClick={runPreview} disabled={previewing || !keyValue.trim() || !mapping.some((mM) => mM.layer_table)}
              className="w-full px-3 py-2 rounded-md text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-1.5 mt-1">
              {previewing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCcw className="w-3.5 h-3.5" />}
              Generate update plan
            </button>
            {previewErr && <p className="text-[11px] text-red-600">{previewErr}</p>}
          </div>
        )}

        {preview && !commitResult && (
          <div className="border border-blue-200 bg-blue-50/40 rounded-lg p-3 space-y-2">
            <p className="text-[11px] font-bold text-gray-700 flex items-center gap-1">
              <ExternalLink className="w-3 h-3 text-blue-600" /> 4. Review plan ({planRows.length} layer{planRows.length === 1 ? "" : "s"})
            </p>
            {(preview.unresolved || []).length > 0 && (
              <div className="rounded-md bg-amber-50 border border-amber-200 p-2 text-[11px] text-amber-700">
                <p className="font-semibold flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> Unclassified layer(s) need a mode below:
                  {(preview.unresolved || []).map((u, i) => <span key={i} className="font-bold"> {layerLabel(u)}{i < (preview.unresolved || []).length - 1 ? "," : ""}</span>)}
                </p>
              </div>
            )}
            {(preview.missing_related || []).length > 0 && (
              <div className="rounded-md bg-amber-50 border border-amber-200 p-2 text-[11px] text-amber-700 space-y-1">
                <p className="flex items-start gap-1"><AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  <span>This request also has geometry in: {(preview.missing_related || []).map(layerLabel).join(", ")}. Updating without these may break spatial alignment.</span>
                </p>
                <label className="flex items-center gap-1.5 font-semibold cursor-pointer">
                  <input type="checkbox" checked={proceedMissing} onChange={(e) => setProceedMissing(e.target.checked)} />
                  Proceed without these layers
                </label>
              </div>
            )}
            {planRows.map((l, i) => {
              const needsMode = l.role === "unclassified";
              const currentMode = modeOf(l.layer_table);
              return (
                <div key={i} className="rounded-md bg-white border border-gray-200 p-2 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-xs font-semibold text-gray-700 truncate">{layerLabel(l.layer_table)}</span>
                      {l.file_base && <span className="text-[10px] text-gray-400 font-mono truncate">{l.file_base}</span>}
                    </div>
                    <span className={"text-[10px] px-1.5 py-0.5 rounded-full font-semibold flex-shrink-0 " + sevClass(l.severity)}>
                      {l.mode_label || l.mode || "Requires classification"}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-wrap">
                    <span>{l.old_count ?? 0} → {l.file_count ?? 0} features</span>
                    {l.gtype && <span>{l.gtype}</span>}
                    {l.inherit_note && <span className="text-gray-400">{l.inherit_note}</span>}
                  </div>
                  {l.confirm && <p className="text-[11px] text-gray-600">{l.confirm}</p>}
                  {l.crs_note && <p className="text-[10px] text-amber-600">{l.crs_note}</p>}
                  {needsMode && (
                    <div className="flex items-center gap-1.5 pt-1">
                      <select value={currentMode} onChange={(e) => setMode(l.layer_table, e.target.value)}
                        className="border border-gray-300 rounded text-xs px-1.5 py-1 flex-1">
                        <option value="">-- choose mode --</option>
                        {MODE_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                      </select>
                      <label className={"flex items-center gap-1 text-[11px] font-semibold " + (currentMode ? "text-gray-600 cursor-pointer" : "text-gray-300")}>
                        <input type="checkbox" checked={!!persistClass[l.layer_table]} disabled={!currentMode}
                          onChange={(e) => togglePersist(l.layer_table, e.target.checked)} /> persist
                      </label>
                    </div>
                  )}
                </div>
              );
            })}
            <button onClick={runCommit}
              disabled={committing || pendingUnresolved.length > 0}
              className="w-full px-3 py-2 rounded-md text-xs font-bold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 flex items-center justify-center gap-1.5">
              {committing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              Commit update
            </button>
            {pendingUnresolved.length > 0 && !committing && (
              <p className="text-[11px] text-amber-700">Resolve unclassified layers above before committing.</p>
            )}
            {commitErr && <p className="text-[11px] text-red-600">{commitErr}</p>}
          </div>
        )}

        {commitResult && (
          <div className="border border-emerald-200 bg-emerald-50 rounded-lg p-3 space-y-2">
            <p className="text-[11px] font-bold text-emerald-700 flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5" /> Committed — request "{keyValue}"
            </p>
            {commitResult.message && <p className="text-[11px] text-emerald-700">{commitResult.message}</p>}
            {summaryRows.map((s, i) => {
              const arc = archiveRows.find((x) => x.layer_table === s.layer_table);
              return (
                <div key={i} className="flex items-center justify-between rounded-md bg-white border border-emerald-100 px-2 py-1.5 gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-gray-700 truncate">{layerLabel(s.layer_table)}</p>
                    <p className="text-[10px] text-gray-400">{s.action} · {s.status} · {s.old_count ?? 0} → {s.new_count ?? 0}</p>
                  </div>
                  {arc && arc.archive_id != null && (
                    <button onClick={() => runUndo(arc.archive_id)} disabled={undoing === arc.archive_id}
                      className="flex-shrink-0 px-2 py-1 rounded-md text-[11px] font-semibold bg-white border border-amber-300 text-amber-700 hover:bg-amber-50 disabled:opacity-50 flex items-center gap-1">
                      {undoing === arc.archive_id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Undo2 className="w-3 h-3" />} Undo
                    </button>
                  )}
                </div>
              );
            })}
            {undoNote && undoNote.archive_id != null && (
              <p className="text-[11px] text-emerald-700">Undone archive #{undoNote.archive_id} ({undoNote.status || "undone"}).</p>
            )}
          </div>
        )}

        {showHistory && (
          <div className="border border-gray-200 rounded-lg p-3 space-y-1.5">
            <p className="text-[11px] font-bold text-gray-600 flex items-center gap-1">
              <History className="w-3 h-3 text-blue-600" /> Update history
            </p>
            {historyErr && <p className="text-[11px] text-red-600">{historyErr}</p>}
            {history && (history.items || []).map((h) => (
              <div key={h.id} className="rounded-md bg-gray-50 px-2 py-1.5 space-y-0.5">
                <div className="flex items-center justify-between text-[11px] gap-2">
                  <span className="font-semibold text-gray-700 truncate">{layerLabel(h.layer_table)}</span>
                  <span className={"text-[10px] px-1.5 py-0.5 rounded-full font-semibold flex-shrink-0 " + (h.undone_at ? "bg-gray-200 text-gray-500" : "bg-emerald-100 text-emerald-700")}>
                    {h.undone_at ? "undone" : h.action}
                  </span>
                </div>
                <p className="text-[10px] text-gray-400">{h.old_count} → {h.new_count} · {h.key_value} · {h.created_at ? new Date(h.created_at).toLocaleString() : ""}</p>
                {!h.undone_at && (
                  <button onClick={() => runUndo(h.id)} disabled={undoing === h.id}
                    className="text-[10px] font-semibold text-amber-600 hover:text-amber-800 flex items-center gap-0.5">
                    {undoing === h.id ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Undo2 className="w-2.5 h-2.5" />} undo
                  </button>
                )}
              </div>
            ))}
            {history && !(history.items || []).length && (
              <p className="text-[11px] text-gray-400">No updates recorded yet.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}