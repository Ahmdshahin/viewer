import React, { useState, useEffect } from "react";
import axios from "axios";
import { useConfirm } from "../components/ConfirmModal";
import { Server, Save, RefreshCw, CheckCircle, AlertTriangle, Trash2, PlusCircle, DatabaseBackup, Clock, FolderOpen, Play, CalendarClock } from "lucide-react";

const DbSettings = () => {
  const [form, setForm] = useState({ host: "", port: 5432, user: "", password: "", db: "" });
  const [current, setCurrent] = useState(null);
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [askConfirm, confirmModal] = useConfirm();

  const headers = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}` });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const load = async () => {
    try {
      const res = await axios.get("/api/v1/admin/db/connection", { headers: headers() });
      setCurrent(res.data);
      setForm({ host: res.data.host, port: res.data.port, user: res.data.user, password: "", db: res.data.db });
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to load connection");
    }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => { fetchMapLayers(); }, []);

  // ---- Scheduled backups (admin) ----
  const [backup, setBackup] = useState(null);
  const [bkForm, setBkForm] = useState({
    enabled: false, mode: "daily", time: "02:00", interval_hours: 24, path: "", keep_days: 14,
    pg_dump_path: "",
  });
  const [bkSaving, setBkSaving] = useState(false);
  const [bkStarting, setBkStarting] = useState(false);
  const [bkMsg, setBkMsg] = useState(null);

  const loadBackup = async () => {
    try {
      const res = await axios.get("/api/v1/admin/db/backup", { headers: headers() });
      setBackup(res.data);
      return res.data;
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to load backup settings");
      return null;
    }
  };

  useEffect(() => {
    axios.get("/api/v1/admin/db/backup", { headers: headers() })
      .then((res) => {
        setBackup(res.data);
        const c = res.data.config || {};
        setBkForm({
          enabled: !!c.enabled,
          mode: c.mode || "daily",
          time: c.time || "02:00",
          interval_hours: c.interval_hours || 24,
          path: c.path || "",
          keep_days: c.keep_days ?? 14,
          pg_dump_path: c.pg_dump_path || "",
        });
      })
      .catch((err) => setError(err.response?.data?.detail || err.message || "Failed to load backup settings"));
  }, []);

  // While a dump is running keep the status panel fresh.
  useEffect(() => {
    if (!backup?.running) return;
    const id = setInterval(loadBackup, 2500);
    return () => clearInterval(id);
  }, [backup?.running]);

  const saveBackup = async () => {
    setBkSaving(true);
    setError(null);
    setBkMsg(null);
    try {
      const res = await axios.put("/api/v1/admin/db/backup", {
        enabled: !!bkForm.enabled,
        mode: bkForm.mode,
        time: bkForm.time || "02:00",
        interval_hours: Number(bkForm.interval_hours) || 24,
        path: bkForm.path,
        keep_days: Number(bkForm.keep_days) || 0,
        pg_dump_path: (bkForm.pg_dump_path || "").trim() || null,
      }, { headers: headers() });
      setBackup(res.data);
      setBkForm((f) => ({ ...f, path: res.data.config.path }));
      setBkMsg({ ok: true, text: "Backup schedule saved." });
    } catch (err) {
      setBkMsg({ ok: false, text: err.response?.data?.detail || err.message || "Failed to save backup schedule" });
    } finally {
      setBkSaving(false);
    }
  };

  const runBackupNow = async () => {
    setBkStarting(true);
    setBkMsg(null);
    try {
      await axios.post("/api/v1/admin/db/backup/run", {}, { headers: headers() });
      setBkMsg({ ok: true, text: "Backup started — admins will be notified when it finishes." });
      setBackup((b) => (b ? { ...b, running: true } : b));
      setTimeout(loadBackup, 3000);
    } catch (err) {
      setBkMsg({ ok: false, text: err.response?.data?.detail || err.message || "Failed to start backup" });
    } finally {
      setBkStarting(false);
    }
  };

  const deleteBackupFile = (f) => askConfirm({
    title: "Delete backup file?",
    message: `Delete "${f.name}"?\nThis cannot be undone.`,
    confirmLabel: "Delete",
    danger: true,
    onConfirm: async () => {
      try {
        await axios.delete("/api/v1/admin/db/backup/file", {
          params: { name: f.name }, headers: headers(),
        });
        setBkMsg({ ok: true, text: "Backup file deleted." });
        loadBackup();
      } catch (err) {
        setBkMsg({ ok: false, text: err.response?.data?.detail || err.message || "Failed to delete backup file" });
      }
    },
  });

  const fmtSize = (n) => {
    if (!n) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let v = Number(n), i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return `${i === 0 ? v : v.toFixed(1)} ${units[i]}`;
  };
  const fmtWhen = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleString();
  };
  const bkCfg = backup?.config;

  // Map layers curation (admin): which DB tables appear in the map viewer
  const [mapLayers, setMapLayers] = useState([]);
  const [savingLayers, setSavingLayers] = useState(false);
  const fetchMapLayers = async () => {
    try {
      const res = await axios.get("/api/v1/admin/db/map-layers", { headers: headers() });
      setMapLayers(res.data.layers || []);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to load map layers");
    }
  };
  const saveMapLayers = async () => {
    setSavingLayers(true);
    setError(null);
    try {
      await axios.post("/api/v1/admin/db/map-layers",
        mapLayers.filter((l) => !l.missing).map((l) => ({
          table: l.table, label: l.label, visible: !!l.visible, color: l.color || "#3388ff",
        })),
        { headers: headers() });
      setSuccess("Map layers saved — the map viewer follows on next load.");
      fetchMapLayers();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to save map layers");
    } finally {
      setSavingLayers(false);
    }
  };
  const deleteLayer = (l) => askConfirm({
    title: "Remove layer?",
    message: `Remove "${l.label || l.table}" from the map list?\nThe database table stays intact — you can re-add it anytime.`,
    confirmLabel: "Remove",
    danger: true,
    onConfirm: async () => {
      setError(null);
      try {
        await axios.delete(`/api/v1/admin/db/map-layers/${encodeURIComponent(l.table)}`, { headers: headers() });
        setSuccess("Layer removed from the map list.");
        fetchMapLayers();
      } catch (err) {
        setError(err.response?.data?.detail || err.message || "Failed to remove layer");
      }
    },
  });
  const [addTable, setAddTable] = useState("");
  const addLayer = async () => {
    const t = mapLayers.find((l) => l.table === addTable && !l.curated && !l.missing);
    if (!t) return;
    setSavingLayers(true);
    setError(null);
    try {
      const palette = ["#e74c3c", "#3498db", "#27ae60", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#8e44ad"];
      const curatedNow = mapLayers.filter((l) => l.curated && !l.missing);
      const body = curatedNow.concat({ table: t.table, label: t.table, visible: true, color: palette[curatedNow.length % palette.length] })
        .map((l) => ({ table: l.table, label: l.label, visible: !!l.visible, color: l.color || "#3388ff" }));
      await axios.post("/api/v1/admin/db/map-layers", body, { headers: headers() });
      setSuccess("Layer added — refresh the map to see it.");
      setAddTable("");
      fetchMapLayers();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to add layer");
    } finally {
      setSavingLayers(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      const res = await axios.post("/api/v1/admin/db/test", {
        host: form.host, port: Number(form.port), user: form.user,
        password: form.password || undefined, db: form.db,
      }, { headers: headers() });
      setTestResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Connection test failed");
    } finally {
      setTesting(false);
    }
  };

  const save = () => askConfirm({
    title: "Switch database?",
    message: "Switch the application to this Postgres database now?\nAll screens will immediately use the new connection.",
    confirmLabel: "Save & switch",
    danger: false,
    onConfirm: () => doSave(),
  });
  const doSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await axios.post("/api/v1/admin/db/connection", {
        host: form.host, port: Number(form.port), user: form.user,
        password: form.password || undefined, db: form.db,
      }, { headers: headers() });
      setCurrent(res.data);
      setForm((f) => ({ ...f, password: "" }));
      setSuccess("Connection switched — the whole system now uses the new database.");
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to save connection");
    } finally {
      setSaving(false);
    }
  };

  const field = (label, key, type, placeholder, autoComplete) => (
    <div>
      <label className="block text-xs font-semibold text-gray-600 mb-1">{label}</label>
      <input
        type={type || "text"}
        value={form[key]}
        onChange={set(key)}
        placeholder={placeholder}
        autoComplete={autoComplete || "off"}
        className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500 bg-white"
      />
    </div>
  );

  return (
    <div className="p-6 h-[calc(100vh-4rem)] overflow-y-auto bg-slate-50">
      <div className="max-w-[1500px] mx-auto space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-800 flex items-center mb-1">
            <Server className="w-6 h-6 mr-3 text-blue-600" />
            Database Connection
          </h1>
          <p className="text-sm text-gray-500">Admin only. Switching applies instantly to the whole system — no restart needed. The password is never displayed.</p>
        </div>

        {error && (
          <div className="p-3 bg-red-100 text-red-700 rounded-md flex items-center text-sm mb-3">
            <AlertTriangle className="w-5 h-5 mr-2 flex-shrink-0" />
            <span className="whitespace-pre-wrap">{error}</span>
          </div>
        )}
        {success && (
          <div className="p-3 bg-emerald-100 text-emerald-800 rounded-md flex items-center font-medium text-sm mb-3">
            <CheckCircle className="w-5 h-5 mr-2" />
            {success}
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* Connection panel */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 flex flex-col">
            {current && (
              <div className="rounded-md bg-slate-50 border border-gray-100 px-3 py-2 mb-4 text-sm flex-shrink-0">
                <span className="text-xs font-bold text-gray-500 uppercase tracking-wider">Active now: </span>
                <span className="font-mono text-gray-800 break-all">{current.database_url}</span>
              </div>
            )}

            <div className="space-y-4 flex-shrink-0">
              <div className="grid grid-cols-2 gap-4">
                {field("Host", "host", "text", "localhost")}
                {field("Port", "port", "number", "5432")}
              </div>
              <div className="grid grid-cols-2 gap-4">
                {field("User", "user", "text", "postgres")}
                {field("Database", "db", "text", "Taqnen_data")}
              </div>
              {field("Password (leave blank to keep current)", "password", "password", "••••••••", "new-password")}

              <div className="flex gap-3 pt-1">
                <button onClick={test} disabled={testing || saving} className="px-4 py-2 bg-slate-200 text-slate-700 hover:bg-slate-300 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50">
                  <RefreshCw className={"w-4 h-4 mr-2 " + (testing ? "animate-spin" : "")} />
                  {testing ? "Testing..." : "Test connection"}
                </button>
                <button onClick={save} disabled={testing || saving} className="px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50">
                  <Save className="w-4 h-4 mr-2" />
                  {saving ? "Saving..." : "Save & switch"}
                </button>
              </div>

              {testResult && testResult.ok && (
                <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-md text-sm text-emerald-800">
                  <p className="font-semibold flex items-center"><CheckCircle className="w-4 h-4 mr-1" /> Connection OK</p>
                  <p className="mt-1 text-xs">Tables found: {testResult.tables_found.join(", ") || "none"}</p>
                  {testResult.missing_tables.length > 0 && (
                    <p className="mt-1 text-xs text-amber-700">Missing geoportal tables (save will be refused): {testResult.missing_tables.join(", ")}</p>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Map layers panel */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 flex flex-col min-h-0">
            <h2 className="text-lg font-semibold text-gray-800 mb-1 flex-shrink-0">Map Layers</h2>
            <p className="text-sm text-gray-500 mb-3 flex-shrink-0">Choose which database tables appear as layers in the map viewer, with labels and colors.</p>
            <div className="flex-1 overflow-y-auto min-h-0 space-y-2 pr-1 max-h-72 xl:max-h-none">
              {mapLayers.map((l) => (
                <div key={l.table} className="flex items-center gap-3 border border-gray-100 rounded-lg px-3 py-2">
                  <input
                    type="checkbox"
                    checked={!!l.visible}
                    disabled={!!l.missing}
                    onChange={(e) => setMapLayers(mapLayers.map((x) => x.table === l.table ? { ...x, visible: e.target.checked } : x))}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    title="Visible in map"
                  />
                  <input
                    type="color"
                    value={l.color || "#3388ff"}
                    disabled={!l.curated || !!l.missing}
                    onChange={(e) => setMapLayers(mapLayers.map((x) => x.table === l.table ? { ...x, color: e.target.value } : x))}
                    className="w-7 h-7 rounded-full cursor-pointer bg-transparent border border-gray-200 p-0 flex-shrink-0 disabled:opacity-30"
                    title="Layer color"
                  />
                  <input
                    type="text"
                    value={l.label}
                    disabled={!l.curated || !!l.missing}
                    onChange={(e) => setMapLayers(mapLayers.map((x) => x.table === l.table ? { ...x, label: e.target.value } : x))}
                    className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-50 disabled:text-gray-400"
                  />
                  <span className="text-[11px] text-gray-500 font-mono flex-shrink-0 hidden md:inline">{l.table}</span>
                  <span className="text-[11px] font-bold text-gray-500 bg-gray-100 rounded-full px-2 py-0.5 flex-shrink-0">{l.count} feats</span>
                  {l.missing && (
                    <span className="text-[11px] font-bold text-red-600 flex-shrink-0">table gone</span>
                  )}
                  {l.curated ? (
                    <button
                      onClick={() => deleteLayer(l)}
                      className="flex-shrink-0 p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                      title="Remove layer from map list"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  ) : (
                    <button
                      onClick={() => { setMapLayers(mapLayers.map((x) => x.table === l.table ? { ...x, curated: true, visible: true, label: x.label || x.table } : x)); }}
                      className="flex-shrink-0 px-2 py-1 rounded text-[11px] font-semibold bg-green-50 text-green-700 hover:bg-green-100 border border-green-200"
                      title="Add as map layer"
                    >
                      <PlusCircle className="w-3.5 h-3.5 mr-1 inline" /> Add
                    </button>
                  )}
                </div>
              ))}
              {mapLayers.length === 0 && (
                <p className="text-sm text-gray-400">Loading tables...</p>
              )}
            </div>
            <div className="mt-3 flex items-center gap-2 flex-shrink-0 border-t border-gray-100 pt-3">
              <select
                value={addTable}
                onChange={(e) => setAddTable(e.target.value)}
                className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm text-gray-700"
              >
                <option value="">New spatial table…</option>
                {mapLayers.filter((l) => !l.curated && !l.missing).map((l) => (
                  <option key={l.table} value={l.table}>{l.table} ({l.count} feats)</option>
                ))}
              </select>
              <button onClick={addLayer} disabled={savingLayers || !addTable} className="px-3 py-1.5 bg-slate-900 text-white hover:bg-slate-700 rounded-md text-sm font-semibold inline-flex items-center shadow-sm disabled:opacity-40">
                <PlusCircle className="w-4 h-4 mr-1.5" /> Add
              </button>
            </div>
            <button onClick={saveMapLayers} disabled={savingLayers} className="mt-3 px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50 flex-shrink-0">
              <Save className="w-4 h-4 mr-2" />
              {savingLayers ? "Saving..." : "Save map layers"}
            </button>
          </div>
        </div>

        {/* Scheduled backup panel */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="flex items-start justify-between gap-3 flex-wrap mb-4">
            <div>
              <h2 className="text-lg font-semibold text-gray-800 flex items-center">
                <DatabaseBackup className="w-5 h-5 mr-2 text-blue-600" /> Scheduled backup
              </h2>
              <p className="text-sm text-gray-500 mt-0.5">
                Automatic <span className="font-mono text-xs">pg_dump</span> (.bak) of{" "}
                <span className="font-mono text-xs">{current?.db || "the active database"}</span>.
                Admins receive a bell notification after every run.
              </p>
            </div>
            <span className={"px-2.5 py-1 rounded-full text-xs font-semibold border " + (backup?.running ? "bg-blue-50 text-blue-700 border-blue-200" : bkForm.enabled ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-gray-100 text-gray-500 border-gray-200")}>
              {backup?.running ? "Backup running…" : bkForm.enabled ? "Schedule on" : "Schedule off"}
            </span>
          </div>

          {backup && (
            <div className={"mb-3 px-3 py-2 rounded-md border text-xs flex flex-wrap items-center gap-x-2 gap-y-1 " +
              (!backup.pg_dump || backup.pg_dump_compatible === false
                ? "bg-amber-50 border-amber-200 text-amber-800"
                : "bg-slate-50 border-gray-200 text-gray-600")}>
              {!backup.pg_dump ? (
                <>
                  <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                  <span>pg_dump was not found on this server. Install the PostgreSQL client tools or add pg_dump to PATH.</span>
                </>
              ) : backup.pg_dump_compatible === false ? (
                <>
                  <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                  <span>
                    pg_dump <b>{backup.pg_dump_version}</b> is older than the database server <b>{backup.server_version}</b>.
                    Install PostgreSQL {String(backup.server_version || "").split(".")[0]}+ client tools, or set a newer path under Advanced.
                  </span>
                </>
              ) : (
                <>
                  <CheckCircle className="w-4 h-4 flex-shrink-0 text-emerald-600" />
                  <span>pg_dump <b>{backup.pg_dump_version}</b></span>
                  <span className="text-gray-300">·</span>
                  <span>server <b>{backup.server_version || "unknown"}</b></span>
                  {backup.pg_dump_compatible !== null && <span className="text-emerald-700 font-medium">compatible</span>}
                  <span className="font-mono text-[10px] text-gray-400 break-all" title={backup.pg_dump}>{backup.pg_dump}</span>
                </>
              )}
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Schedule form */}
            <div className="space-y-3">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={!!bkForm.enabled}
                  onChange={(e) => setBkForm((f) => ({ ...f, enabled: e.target.checked }))}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm font-medium text-gray-700">Run automatic backups</span>
              </label>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-600 mb-1">Frequency</label>
                  <select
                    value={bkForm.mode}
                    onChange={(e) => setBkForm((f) => ({ ...f, mode: e.target.value }))}
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm bg-white focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="daily">Daily at a time</option>
                    <option value="interval">Every N hours</option>
                  </select>
                </div>
                {bkForm.mode === "daily" ? (
                  <div>
                    <label className="text-xs font-semibold text-gray-600 mb-1 flex items-center">
                      <Clock className="w-3.5 h-3.5 mr-1" /> Time (server local)
                    </label>
                    <input
                      type="time"
                      value={bkForm.time}
                      onChange={(e) => setBkForm((f) => ({ ...f, time: e.target.value }))}
                      className="w-full border border-gray-300 rounded px-3 py-2 text-sm bg-white focus:ring-blue-500 focus:border-blue-500"
                    />
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs font-semibold text-gray-600 mb-1">Every (hours)</label>
                    <input
                      type="number"
                      min={1}
                      max={168}
                      value={bkForm.interval_hours}
                      onChange={(e) => setBkForm((f) => ({ ...f, interval_hours: e.target.value }))}
                      className="w-full border border-gray-300 rounded px-3 py-2 text-sm bg-white focus:ring-blue-500 focus:border-blue-500"
                    />
                  </div>
                )}
              </div>

              <div>
                <label className="text-xs font-semibold text-gray-600 mb-1 flex items-center">
                  <FolderOpen className="w-3.5 h-3.5 mr-1" /> Backup folder (server path)
                </label>
                <input
                  type="text"
                  value={bkForm.path}
                  onChange={(e) => setBkForm((f) => ({ ...f, path: e.target.value }))}
                  placeholder={"D:\\Backups\\GeoPortal"}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono bg-white focus:ring-blue-500 focus:border-blue-500"
                />
                <p className="text-[11px] text-gray-500 mt-1">Created automatically if it does not exist. Files are written as <span className="font-mono">&lt;db&gt;_YYYYmmdd_HHMMSS.bak</span>.</p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Delete backups older than (days)</label>
                <input
                  type="number"
                  min={0}
                  max={3650}
                  value={bkForm.keep_days}
                  onChange={(e) => setBkForm((f) => ({ ...f, keep_days: e.target.value }))}
                  className="w-32 border border-gray-300 rounded px-3 py-2 text-sm bg-white focus:ring-blue-500 focus:border-blue-500"
                />
                <span className="text-[11px] text-gray-500 ml-2">0 = keep every backup</span>
              </div>

              <details className="rounded-md border border-gray-100 bg-slate-50 px-3 py-2">
                <summary className="text-xs font-semibold text-gray-600 cursor-pointer select-none">Advanced: pg_dump path</summary>
                <input
                  type="text"
                  value={bkForm.pg_dump_path}
                  onChange={(e) => setBkForm((f) => ({ ...f, pg_dump_path: e.target.value }))}
                  placeholder={"(auto) C:\\Program Files\\PostgreSQL\\18\\bin\\pg_dump.exe"}
                  className="mt-2 w-full border border-gray-300 rounded px-3 py-2 text-xs font-mono bg-white focus:ring-blue-500 focus:border-blue-500"
                />
                <p className="text-[11px] text-gray-500 mt-1">
                  Leave empty to auto-pick. pg_dump must be the <b>same major version or newer</b> than the database server — a newer pg_dump can always dump an older server.
                </p>
                {(backup?.pg_dump_candidates || []).length > 1 && (
                  <p className="text-[11px] text-gray-500 mt-1 font-mono">
                    Detected: {backup.pg_dump_candidates.map((c) => c.version || c.path).join(" · ")}
                  </p>
                )}
              </details>

              <div className="flex flex-wrap gap-2 pt-1">
                <button
                  onClick={saveBackup}
                  disabled={bkSaving || bkStarting || !bkForm.path.trim()}
                  className="px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50"
                >
                  <Save className="w-4 h-4 mr-2" />
                  {bkSaving ? "Saving..." : "Save schedule"}
                </button>
                <button
                  onClick={runBackupNow}
                  disabled={bkSaving || bkStarting || backup?.running}
                  className="px-4 py-2 bg-slate-900 text-white hover:bg-slate-700 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50"
                  title="Run a backup right now, regardless of the schedule"
                >
                  {backup?.running ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
                  {backup?.running ? "Backup running..." : "Run backup now"}
                </button>
              </div>

              {bkMsg && (
                <p className={"text-xs font-medium flex items-start " + (bkMsg.ok ? "text-emerald-700" : "text-red-600")}>
                  {bkMsg.ok ? <CheckCircle className="w-4 h-4 mr-1 flex-shrink-0" /> : <AlertTriangle className="w-4 h-4 mr-1 flex-shrink-0" />}
                  {bkMsg.text}
                </p>
              )}
            </div>

            {/* Status + files */}
            <div className="space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div className="rounded-md border border-gray-100 bg-slate-50 px-3 py-2">
                  <div className="text-[11px] font-bold text-gray-500 uppercase tracking-wider flex items-center">
                    <CalendarClock className="w-3.5 h-3.5 mr-1" /> Next run
                  </div>
                  <div className="text-sm text-gray-800 mt-0.5">{bkForm.enabled ? fmtWhen(bkCfg?.next_run) : "Disabled"}</div>
                </div>
                <div className={"rounded-md border px-3 py-2 " + (bkCfg?.last_status === "error" ? "border-red-200 bg-red-50" : "border-gray-100 bg-slate-50")}>
                  <div className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">Last run</div>
                  <div className="text-sm text-gray-800 mt-0.5">
                    {bkCfg?.last_run ? (
                      <span className="inline-flex items-center gap-1">
                        {bkCfg.last_status === "ok"
                          ? <CheckCircle className="w-3.5 h-3.5 text-emerald-600" />
                          : <AlertTriangle className="w-3.5 h-3.5 text-red-600" />}
                        {fmtWhen(bkCfg.last_run)}
                      </span>
                    ) : "Never run"}
                  </div>
                  {bkCfg?.last_message && (
                    <div className={"text-[11px] mt-0.5 break-words " + (bkCfg.last_status === "ok" ? "text-gray-500" : "text-red-700")}>
                      {bkCfg.last_message}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-gray-600">
                    Backup files
                    <span className="ml-1.5 font-normal text-gray-400">
                      {backup?.total_files || 0} file(s) · {fmtSize(backup?.total_size || 0)}
                    </span>
                  </span>
                  <button onClick={loadBackup} title="Refresh list" className="p-1 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors">
                    <RefreshCw className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="border border-gray-100 rounded-md max-h-56 overflow-y-auto divide-y divide-gray-50">
                  {(backup?.files || []).map((f) => (
                    <div key={f.name} className="flex items-center gap-2 px-2.5 py-1.5 text-xs hover:bg-slate-50">
                      <span className="flex-1 font-mono text-gray-700 truncate" title={f.name}>{f.name}</span>
                      <span className="text-gray-400 flex-shrink-0">{fmtSize(f.size)}</span>
                      <span className="text-gray-400 flex-shrink-0 hidden sm:inline">{fmtWhen(f.mtime)}</span>
                      <button
                        onClick={() => deleteBackupFile(f)}
                        className="flex-shrink-0 p-1 rounded text-gray-300 hover:text-red-600 hover:bg-red-50 transition-colors"
                        title="Delete this backup file"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                  {(backup?.files || []).length === 0 && (
                    <p className="px-3 py-6 text-center text-xs text-gray-400">
                      {backup?.folder_exists ? "No .bak files in this folder yet." : "Backup folder does not exist yet."}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
        {confirmModal}
      </div>
    </div>
  );
};

export default DbSettings;
