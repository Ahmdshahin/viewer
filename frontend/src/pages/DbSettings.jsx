import React, { useState, useEffect } from "react";
import axios from "axios";
import { useConfirm } from "../components/ConfirmModal";
import { Server, Save, RefreshCw, CheckCircle, AlertTriangle } from "lucide-react";

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
      <div className="max-w-2xl mx-auto">
        <h1 className="text-2xl font-bold text-gray-800 flex items-center mb-1">
          <Server className="w-6 h-6 mr-3 text-blue-600" />
          Database Connection
        </h1>
        <p className="text-sm text-gray-500 mb-4">Admin only. Switching applies instantly to the whole system — no restart needed. The password is never displayed.</p>

        {error && (
          <div className="p-3 bg-red-100 text-red-700 rounded-md flex items-center text-sm mb-4">
            <AlertTriangle className="w-5 h-5 mr-2 flex-shrink-0" />
            <span className="whitespace-pre-wrap">{error}</span>
          </div>
        )}
        {success && (
          <div className="p-3 bg-emerald-100 text-emerald-800 rounded-md flex items-center font-medium text-sm mb-4">
            <CheckCircle className="w-5 h-5 mr-2" />
            {success}
          </div>
        )}

        {current && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 px-4 py-3 mb-4 text-sm">
            <span className="text-xs font-bold text-gray-500 uppercase tracking-wider">Active now: </span>
            <span className="font-mono text-gray-800">{current.database_url}</span>
          </div>
        )}

        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 space-y-4">
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
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mt-4">
          <h2 className="text-lg font-semibold text-gray-800 mb-1">Map Layers</h2>
          <p className="text-sm text-gray-500 mb-3">Choose which database tables appear as layers in the map viewer, with labels and colors.</p>
          <div className="space-y-2">
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
                  onChange={(e) => setMapLayers(mapLayers.map((x) => x.table === l.table ? { ...x, color: e.target.value } : x))}
                  className="w-7 h-7 rounded-full cursor-pointer bg-transparent border border-gray-200 p-0 flex-shrink-0"
                  title="Layer color"
                />
                <input
                  type="text"
                  value={l.label}
                  onChange={(e) => setMapLayers(mapLayers.map((x) => x.table === l.table ? { ...x, label: e.target.value } : x))}
                  className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-blue-500 focus:border-blue-500"
                />
                <span className="text-[11px] text-gray-500 font-mono flex-shrink-0">{l.table}</span>
                <span className="text-[11px] font-bold text-gray-500 bg-gray-100 rounded-full px-2 py-0.5 flex-shrink-0">{l.count} feats</span>
                {l.missing && (
                  <span className="text-[11px] font-bold text-red-600 flex-shrink-0">table gone</span>
                )}
              </div>
            ))}
            {mapLayers.length === 0 && (
              <p className="text-sm text-gray-400">Loading tables...</p>
            )}
          </div>
          <button onClick={saveMapLayers} disabled={savingLayers} className="mt-3 px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50">
            <Save className="w-4 h-4 mr-2" />
            {savingLayers ? "Saving..." : "Save map layers"}
          </button>
        </div>
        {confirmModal}
      </div>
    </div>
  );
};

export default DbSettings;
