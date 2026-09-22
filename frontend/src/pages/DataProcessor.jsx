import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useConfirm } from "../components/ConfirmModal";
import { Database, AlertTriangle, Play, RefreshCw, FolderSearch, FolderOpen, Save, FileJson, Archive, Terminal, CheckCircle, Search, Download, Trash2, X, ChevronDown, ChevronRight } from 'lucide-react';

const DataProcessor = () => {
  const [scanData, setScanData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [resultTab, setResultTab] = useState("ready"); // "ready" | "done" | "conflicts"
  const [expandedGroups, setExpandedGroups] = useState({}); // reason -> bool (first group open by default)
  const [step, setStep] = useState(1); // wizard: 1 paths, 2 review, 3 run, 4 migrate to PostGIS
  const [pipelineRan, setPipelineRan] = useState(false); // step 4 unlocks only after a successful run
  const [askConfirm, confirmModal] = useConfirm();
  const [bulkReplace, setBulkReplace] = useState(null); // {reason, done, total} while replace-all runs
  
  // Progress state
  const [progress, setProgress] = useState({ status: "idle", total: 0, processed: 0, current_folder: "", percentage: 0, logs: [] });
  const logsEndRef = useRef(null);

  // Path configurations
  const [inputPath, setInputPath] = useState("d:\\Systems\\SHP_Files(2)");
  const [outputGpkg, setOutputGpkg] = useState("d:\\\\Systems\\\\MapViewer\\\\Unified_Database.gpkg");
  const [doneDir, setDoneDir] = useState("d:\\\\Systems\\\\MapViewer\\\\Done");
  const [conflictsFile, setConflictsFile] = useState("d:\\\\Systems\\\\MapViewer\\\\conflicts.json");

  const scrollToBottom = () => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    if (progress.logs && progress.logs.length > 0) {
      scrollToBottom();
    }
  }, [progress.logs]);

  const handleBrowse = async (type, title, defaultExt, setter) => {
    try {
      const res = await axios.get('/api/v1/processor/browse', {
        params: { type, title, default_ext: defaultExt }
      });
      if (res.data.path) {
        // Normalize slashes for Windows
        setter(res.data.path.replace(/\//g, '\\\\'));
      }
    } catch (err) {
      setError("Failed to open file browser dialog.");
    }
  };

  const exportCSV = () => {
    if (!scanData) return;
    let rows = [];
    let filename = "";
    if (resultTab === "ready") {
      rows.push(["Folder / Request", "Status"]);
      (scanData.pending_folders || []).forEach((f) => rows.push([f, "Ready"]));
      filename = "ready_folders";
    } else if (resultTab === "done") {
      rows.push(["Folder / Request", "Status"]);
      (scanData.done_folders || []).forEach((f) => rows.push([f, "Archived"]));
      filename = "done_folders";
    } else {
      rows.push(["Folder / Request", "Conflict Reason"]);
      (scanData.conflicts || []).forEach((c) => rows.push([c.folder, c.reason]));
      filename = "conflicts";
    }
    const escape = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = "\uFEFF" + rows.map((r) => r.map(escape).join(",")).join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // Group conflicts by problem (reason), biggest group first
  const groupConflicts = (list) => {
    const map = new Map();
    (list || []).forEach((c) => {
      const key = c.reason || "Unknown problem";
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(c);
    });
    return [...map.entries()]
      .map(([reason, items]) => ({ reason, items }))
      .sort((a, b) => b.items.length - a.items.length);
  };
  const toggleGroup = (reason) => setExpandedGroups((p) => ({ ...p, [reason]: !p[reason] }));

  const conflictOp = async (fn, okMsg) => {
    setError(null);
    try {
      await fn();
      setSuccess(okMsg);
      fetchScan();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Operation failed");
    }
  };
  const dismissConflict = (c) => conflictOp(
    () => axios.delete('/api/v1/processor/conflicts', {
      data: { folder: c.folder, reason: c.reason },
      params: { conflicts_file: conflictsFile }
    }),
    `Dismissed conflict for ${c.folder}`
  );
  const deleteFolder = (folder) => askConfirm({
    title: "Delete folder?",
    message: `Permanently delete input folder "${folder}"?\nThis cannot be undone.`,
    confirmLabel: "Delete",
    danger: true,
    onConfirm: () => conflictOp(
      () => axios.delete('/api/v1/processor/folder', {
        params: { folder_name: folder, input_path: inputPath, conflicts_file: conflictsFile }
      }),
      `Deleted folder ${folder}`
    ),
  });
  const dismissGroup = (reason, count) => askConfirm({
    title: "Dismiss conflicts?",
    message: `Dismiss all ${count} conflicts of this problem?\n"${reason}"`,
    confirmLabel: "Dismiss",
    danger: false,
    onConfirm: () => conflictOp(
      () => axios.post('/api/v1/processor/conflicts/clear', { reason }, { params: { conflicts_file: conflictsFile } }),
      `Dismissed ${count} conflicts`
    ),
  });
  const deleteGroupFolders = (items) => askConfirm({
    title: "Delete folders?",
    message: `Permanently delete ${items.length} input folders of this problem?\nThis cannot be undone.`,
    confirmLabel: "Delete all",
    danger: true,
    onConfirm: () => runDeleteGroupFolders(items),
  });
  const runDeleteGroupFolders = async (items) => {
    setError(null);
    try {
      for (const c of items) {
        await axios.delete('/api/v1/processor/folder', {
          params: { folder_name: c.folder, input_path: inputPath, conflicts_file: conflictsFile }
        });
      }
      setSuccess(`Deleted ${items.length} folders`);
      fetchScan();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Operation failed");
      fetchScan();
    }
  };
  const dismissAllConflicts = () => askConfirm({
    title: "Dismiss all conflicts?",
    message: "Dismiss ALL conflicts? Folders stay in place; only the log entries are removed.",
    confirmLabel: "Dismiss all",
    danger: true,
    onConfirm: () => conflictOp(
      () => axios.post('/api/v1/processor/conflicts/clear', {}, { params: { conflicts_file: conflictsFile } }),
      "Dismissed all conflicts"
    ),
  });

  const replaceDuplicate = (c) => askConfirm({
    title: "Replace database rows?",
    message: `Replace database rows for this request with files from "${c.folder}"?\nOld rows will be deleted and the folder re-imported.`,
    confirmLabel: "Replace",
    danger: true,
    onConfirm: () => conflictOp(
      () => axios.post('/api/v1/processor/duplicates/resolve', {
        folder: c.folder, mode: "replace", input_path: inputPath,
        output_gpkg: outputGpkg, done_dir: doneDir, conflicts_file: conflictsFile
      }),
      `Replaced database rows from ${c.folder}`
    ),
  });
  const replaceAllDuplicates = (group) => askConfirm({
    title: "Replace all?",
    message: `Replace database rows for all ${group.items.length} folders in this problem?\nOld rows are deleted and each folder is re-imported, one by one.`,
    confirmLabel: "Replace all",
    danger: true,
    onConfirm: () => runReplaceAll(group),
  });
  const runReplaceAll = async (group) => {
    setError(null);
    setSuccess(null);
    const failed = [];
    for (let i = 0; i < group.items.length; i++) {
      const c = group.items[i];
      setBulkReplace({ reason: group.reason, done: i, total: group.items.length });
      try {
        await axios.post('/api/v1/processor/duplicates/resolve', {
          folder: c.folder, mode: "replace", input_path: inputPath,
          output_gpkg: outputGpkg, done_dir: doneDir, conflicts_file: conflictsFile
        });
      } catch (err) {
        failed.push(c.folder);
      }
    }
    setBulkReplace(null);
    if (failed.length === 0) {
      setSuccess(`Replaced all ${group.items.length} folders.`);
    } else {
      setError(`Replaced ${group.items.length - failed.length}/${group.items.length}. Failed: ${failed.join(", ")}`);
    }
    fetchScan();
  };
  const doEmptyDatabase = async () => {
    setError(null);
    const res = await axios.post('/api/v1/processor/database/clear', {}, { params: { output_gpkg: outputGpkg } });
    const n = res.data.total_removed ?? 0;
    const msg = res.data.emptied ? `Database emptied (${n} features removed).` : (res.data.message || "Database already empty.");
    setSuccess(msg);
    fetchScan();
    return msg;
  };
  const emptyDatabase = () => askConfirm({
    title: "Empty the database?",
    message: "All Land, Eshghalat and Point rows will be permanently deleted.\nThis cannot be undone.",
    confirmLabel: "Empty DB",
    danger: true,
    onConfirm: async () => {
      try {
        await doEmptyDatabase();
      } catch (err) {
        setError(err.response?.data?.detail || err.message || "Operation failed");
      }
    },
  });

  // Step 4: migrate GPKG -> PostGIS with per-user audit
  const [migStatus, setMigStatus] = useState(null);
  const [migHistory, setMigHistory] = useState([]);
  const [migrating, setMigrating] = useState(false);
  const authHeaders = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}` });
  const fetchMigrate = async () => {
    try {
      const [st, hi] = await Promise.all([
        axios.get("/api/v1/processor/migrate/status", { params: { output_gpkg: outputGpkg } }),
        axios.get("/api/v1/processor/migrate/history", { params: { limit: 50 } }),
      ]);
      setMigStatus(st.data);
      setMigHistory(hi.data.history || []);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to load migration status");
    }
  };
  const runMigrate = () => askConfirm({
    title: "Migrate to map?",
    message: "Migrate processed features into the PostGIS map database?\nAlready-migrated requests are skipped, and every layer is logged under your username.",
    confirmLabel: "Migrate",
    danger: false,
    onConfirm: () => doRunMigrate(),
  });
  const doRunMigrate = async () => {
    setMigrating(true);
    setError(null);
    try {
      const res = await axios.post("/api/v1/processor/migrate/run", { output_gpkg: outputGpkg }, { headers: authHeaders() });
      const m = res.data.migrated || {};
      const s = res.data.skipped || {};
      const o = res.data.orphaned || {};
      const doneMsg = `Migrated by ${res.data.migrated_by}: land +${m.land || 0}, eshghalat +${m.eshghalat || 0}, point +${m.point || 0} (skipped: ${s.land || 0}/${s.eshghalat || 0}/${s.point || 0}, orphaned: ${o.land || 0}/${o.eshghalat || 0}/${o.point || 0}).`;
      setSuccess(doneMsg);
      fetchMigrate();
      askConfirm({
        title: "Migration completed",
        message: "Empty the file database now to start a new task?\nThe map data stays untouched. This cannot be undone.",
        confirmLabel: "Empty & new task",
        danger: true,
        onConfirm: async () => {
          try {
            await doEmptyDatabase();
            setSuccess(doneMsg + " File database emptied — ready for the next task.");
            fetchMigrate();
            setStep(1);
          } catch (err) {
            setError(err.response?.data?.detail || err.message || "Operation failed");
          }
        },
      });
    } catch (err) {
      if (err.response && err.response.status === 401) {
        setError("Please log in again to migrate.");
      } else if (err.response && err.response.status === 403) {
        setError("Your role cannot migrate (editors and admins only).");
      } else {
        setError(err.response?.data?.detail || err.message || "Migration failed");
      }
    } finally {
      setMigrating(false);
    }
  };

  const fetchScan = async () => {
    setLoading(true);
    setError(null);
    setSuccess(null);
    setPipelineRan(false);
    try {
      const res = await axios.get('/api/v1/processor/scan', {
        params: { input_path: inputPath, conflicts_file: conflictsFile, done_dir: doneDir }
      });
      if (res.data.error) {
        setError(res.data.error);
        setScanData(null);
        return false;
      } else {
        setScanData(res.data);
        return true;
      }
    } catch (err) {
      if (err.response && err.response.status === 401) {
        localStorage.removeItem('token');
        window.location.reload();
      }
      setError(err.message || "Failed to scan directory");
      return false;
    } finally {
      setLoading(false);
    }
  };

  const pollProgress = async () => {
    try {
      const res = await axios.get('/api/v1/processor/progress');
      setProgress(res.data);
      
      if (res.data.status === "running") {
        setTimeout(pollProgress, 1000);
      } else if (res.data.status === "completed") {
        setRunning(false);
        setSuccess("Pipeline execution completed successfully!");
        fetchScan();
        setPipelineRan(true);
      } else if (res.data.status === "error") {
        setRunning(false);
        setError(res.data.error_detail || "An error occurred during processing.");
      }
    } catch (err) {
      setTimeout(pollProgress, 2000);
    }
  };

  const runPipeline = async () => {
    setRunning(true);
    setError(null);
    setSuccess(null);
    setPipelineRan(false);
    setProgress({ status: "running", total: 0, processed: 0, current_folder: "Initializing...", percentage: 0, logs: ["Starting pipeline..."] });
    
    try {
      const payload = { input_path: inputPath, output_gpkg: outputGpkg, done_dir: doneDir, conflicts_file: conflictsFile };
      await axios.post('/api/v1/processor/run', payload);
      pollProgress();
    } catch (err) {
      setRunning(false);
      setError(err.response?.data?.detail || err.message || "Failed to start pipeline");
    }
  };

  // Attach auth token so destructive actions are audit-attributed to the user
  useEffect(() => {
    try {
      const t = localStorage.getItem("token");
      if (t) axios.defaults.headers.common["Authorization"] = `Bearer ${t}`;
    } catch (e) { /* storage unavailable */ }
  }, []);

  // Persist paths per browser so each workstation keeps its own server paths
  useEffect(() => {
    try {
      const saved = {
        inputPath: localStorage.getItem("dp_inputPath"),
        outputGpkg: localStorage.getItem("dp_outputGpkg"),
        doneDir: localStorage.getItem("dp_doneDir"),
        conflictsFile: localStorage.getItem("dp_conflictsFile"),
      };
      if (saved.inputPath) setInputPath(saved.inputPath);
      if (saved.outputGpkg) setOutputGpkg(saved.outputGpkg);
      if (saved.doneDir) setDoneDir(saved.doneDir);
      if (saved.conflictsFile) setConflictsFile(saved.conflictsFile);
    } catch (e) { /* storage unavailable */ }
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem("dp_inputPath", inputPath);
      localStorage.setItem("dp_outputGpkg", outputGpkg);
      localStorage.setItem("dp_doneDir", doneDir);
      localStorage.setItem("dp_conflictsFile", conflictsFile);
    } catch (e) { /* storage unavailable */ }
  }, [inputPath, outputGpkg, doneDir, conflictsFile]);

  useEffect(() => {
    // On open: start blank (no auto-scan). Only resume if a pipeline is
    // actually still running in the backend.
    const checkInitial = async () => {
      try {
        const res = await axios.get('/api/v1/processor/progress');
        if (res.data.status === "running") {
          setRunning(true);
          setStep(3);
          pollProgress();
        }
      } catch (e) {
        // stay blank until the user clicks Scan
      }
    };
    checkInitial();
  }, []);

  useEffect(() => {
    if (step === 4) fetchMigrate();
  }, [step]);

  return (
    <div className="p-4 h-[calc(100vh-4rem)] flex flex-col bg-slate-50 overflow-hidden">
      
      {/* HEADER */}
      <div className="flex justify-between items-center mb-3 flex-shrink-0">
        <h1 className="text-2xl font-bold text-gray-800 flex items-center">
          <Database className="w-6 h-6 mr-3 text-blue-600" />
          Data Processor
        </h1>
      </div>

      {/* WIZARD STEPPER */}
      <div className="flex items-center mb-4 flex-shrink-0 bg-white rounded-lg shadow-sm border border-gray-200 px-6 py-3">
        {[
          { n: 1, label: "Source paths" },
          { n: 2, label: "Review results" },
          { n: 3, label: "Run pipeline" },
          { n: 4, label: "Migrate to map" },
        ].map((s, i, arr) => (
          <React.Fragment key={s.n}>
            <button onClick={() => setStep(s.n)} disabled={running} className="flex items-center gap-2 disabled:cursor-default">
              <span className={"w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold " + (step > s.n ? "bg-emerald-600 text-white" : step === s.n ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-500")}>
                {step > s.n ? <CheckCircle className="w-4 h-4" /> : s.n}
              </span>
              <span className={"text-sm font-semibold " + (step === s.n ? "text-gray-900" : "text-gray-500")}>{s.label}</span>
            </button>
            {i < arr.length - 1 && <div className={"flex-1 h-0.5 mx-4 rounded " + (step > s.n ? "bg-emerald-500" : "bg-gray-200")} />}
          </React.Fragment>
        ))}
      </div>

      {/* ERROR / SUCCESS ALERTS */}
      {error && (
        <div className="p-3 bg-red-100 text-red-700 rounded-md flex items-center text-sm mb-4 flex-shrink-0">
          <AlertTriangle className="w-5 h-5 mr-2 flex-shrink-0" />
          <span className="whitespace-pre-wrap font-mono">{error}</span>
        </div>
      )}
      {success && (
        <div className="p-3 bg-emerald-100 text-emerald-800 rounded-md flex items-center font-medium text-sm mb-4 flex-shrink-0">
          <CheckCircle className="w-5 h-5 mr-2" />
          {success}
        </div>
      )}

      {/* MAIN CONTENT PANELS */}
      <div className="flex flex-1 min-h-0 gap-4 flex-col lg:flex-row">
        
        {/* LEFT COLUMN: Config + Stats */}
        <div className="w-full lg:w-1/3 flex flex-col gap-4 min-h-0 flex-shrink-0">
          
          {/* STATS CARDS (step 2) */}
          {step === 2 && scanData && !running && (
            <div className="grid grid-cols-3 gap-4 flex-shrink-0">
              <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-200 flex flex-col justify-center items-center text-center">
                <FolderSearch className="w-6 h-6 text-blue-500 mb-1" />
                <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Pending</p>
                <p className="text-2xl font-bold text-gray-900">{scanData.total_pending}</p>
              </div>
              <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-200 flex flex-col justify-center items-center text-center">
                <FolderOpen className="w-6 h-6 text-emerald-500 mb-1" />
                <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Done</p>
                <p className="text-2xl font-bold text-emerald-600">{scanData.total_done}</p>
              </div>
              <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-200 flex flex-col justify-center items-center text-center">
                <AlertTriangle className="w-6 h-6 text-red-500 mb-1" />
                <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Conflicts</p>
                <p className="text-2xl font-bold text-red-600">{scanData.total_conflicts}</p>
              </div>
            </div>
          )}

          {/* STEP 1: SOURCE PATHS */}
          {step === 1 && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 flex flex-col flex-1 min-h-0">
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center text-sm font-semibold text-gray-700 flex-shrink-0">
              <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold mr-2">1</span>
              Source paths — where to read from and write to
            </div>
            <div className="p-4 overflow-y-auto flex-1 space-y-4">
              <div>
                <label className="flex items-center text-xs font-semibold text-gray-600 mb-1">
                  <FolderOpen className="w-3 h-3 mr-1 text-blue-500" /> Input Directory
                </label>
                <div className="flex">
                  <input type="text" value={inputPath} onChange={(e) => setInputPath(e.target.value)} className="w-full border border-gray-300 rounded-l px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500 bg-gray-50" disabled={running} />
                  <button onClick={() => handleBrowse('folder', 'Select Input Shapefiles Directory', '', setInputPath)} disabled={running} className="bg-gray-200 hover:bg-gray-300 border border-gray-300 border-l-0 rounded-r px-2 py-1.5 text-gray-700 transition-colors">
                    <Search className="w-3 h-3" />
                  </button>
                </div>
              </div>
              <div>
                <label className="flex items-center text-xs font-semibold text-gray-600 mb-1">
                  <Save className="w-3 h-3 mr-1 text-emerald-500" /> Output GeoPackage
                </label>
                <div className="flex">
                  <input type="text" value={outputGpkg} onChange={(e) => setOutputGpkg(e.target.value)} className="w-full border border-gray-300 rounded-l px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500 bg-gray-50" disabled={running} />
                  <button onClick={() => handleBrowse('save_file', 'Select Output GeoPackage', '.gpkg', setOutputGpkg)} disabled={running} className="bg-gray-200 hover:bg-gray-300 border border-gray-300 border-l-0 rounded-r px-2 py-1.5 text-gray-700 transition-colors">
                    <Search className="w-3 h-3" />
                  </button>
                </div>
              </div>
              <div>
                <label className="flex items-center text-xs font-semibold text-gray-600 mb-1">
                  <Archive className="w-3 h-3 mr-1 text-amber-500" /> Archive Directory
                </label>
                <div className="flex">
                  <input type="text" value={doneDir} onChange={(e) => setDoneDir(e.target.value)} className="w-full border border-gray-300 rounded-l px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500 bg-gray-50" disabled={running} />
                  <button onClick={() => handleBrowse('folder', 'Select Done/Archive Directory', '', setDoneDir)} disabled={running} className="bg-gray-200 hover:bg-gray-300 border border-gray-300 border-l-0 rounded-r px-2 py-1.5 text-gray-700 transition-colors">
                    <Search className="w-3 h-3" />
                  </button>
                </div>
              </div>
              <div>
                <label className="flex items-center text-xs font-semibold text-gray-600 mb-1">
                  <FileJson className="w-3 h-3 mr-1 text-red-500" /> Conflicts Log File
                </label>
                <div className="flex">
                  <input type="text" value={conflictsFile} onChange={(e) => setConflictsFile(e.target.value)} className="w-full border border-gray-300 rounded-l px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500 bg-gray-50" disabled={running} />
                  <button onClick={() => handleBrowse('save_file', 'Select Conflicts JSON File', '.json', setConflictsFile)} disabled={running} className="bg-gray-200 hover:bg-gray-300 border border-gray-300 border-l-0 rounded-r px-2 py-1.5 text-gray-700 transition-colors">
                    <Search className="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>
            <div className="px-4 py-3 border-t border-gray-100 bg-gray-50 flex justify-between items-center flex-shrink-0">
              <button onClick={emptyDatabase} disabled={loading || running} title="Delete ALL rows from the file database. This cannot be undone." className="px-4 py-2 bg-white border border-red-300 text-red-600 hover:bg-red-50 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50">
                <Trash2 className="w-4 h-4 mr-2" />
                Empty DB
              </button>
              <button onClick={async () => { const ok = await fetchScan(); if (ok) setStep(2); }} disabled={loading || running} className="px-5 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50">
                <RefreshCw className={"w-4 h-4 mr-2 " + (loading && !running ? "animate-spin" : "")} />
                Scan folders & continue
              </button>
            </div>
          </div>
          )}
          
        </div>

        {/* STEP 2 / STEP 3 PANEL */}
        <div className="w-full lg:w-2/3 flex flex-col min-h-0 bg-white rounded-lg shadow-sm border border-gray-200">
          {step === 3 && !running && (
            <div className="flex flex-col items-center justify-center h-full p-8 text-center">
              <span className="w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-bold mb-3">3</span>
              <h3 className="text-md font-bold text-gray-800 mb-1">Ready to process</h3>
              <p className="text-sm text-gray-600">Import folders into the database and archive them.</p>
              <p className="text-xs text-gray-500 mt-1">Input: <span className="font-mono">{inputPath}</span></p>
              <p className="text-xs text-gray-500">Output: <span className="font-mono">{outputGpkg}</span></p>
              <div className="flex gap-3 mt-5">
                <button onClick={() => setStep(2)} className="px-4 py-2 bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 rounded-md text-sm font-medium transition-colors shadow-sm">
                  Back to review
                </button>
                <button onClick={runPipeline} disabled={loading || running || !scanData} title={!scanData ? "Scan first (step 1) before running" : ""} className="px-5 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50">
                  <Play className="w-4 h-4 mr-2" />
                  Run Pipeline{scanData ? ` (${scanData.total_pending} folders)` : ""}
                </button>
                {pipelineRan && (
                  <button onClick={() => setStep(4)} className="px-4 py-2 bg-emerald-600 text-white hover:bg-emerald-700 rounded-md text-sm font-medium transition-colors shadow-sm">
                    Continue to migrate
                  </button>
                )}
              </div>
              {!scanData && <p className="text-xs text-amber-600 mt-3">No scan data yet — go back to step 1 and scan first.</p>}
            </div>
          )}
          {step === 3 && running ? (
            // PROGRESS TERMINAL
            <div className="flex flex-col h-full p-4">
              <div className="mb-4 flex-shrink-0">
                <h3 className="text-md font-bold text-gray-800 flex items-center mb-2">
                  <RefreshCw className="w-4 h-4 text-blue-600 animate-spin mr-2" />
                  Processing Pipeline Running...
                </h3>
                <div className="flex justify-between text-xs font-medium text-gray-600 mb-1">
                  <span>{progress.processed} / {progress.total} folders</span>
                  <span>{progress.percentage}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                  <div className="bg-blue-600 h-1.5 rounded-full transition-all duration-300 ease-out" style={{ width: progress.percentage + '%' }}></div>
                </div>
              </div>
              
              <div className="bg-gray-900 rounded-md border border-gray-700 flex flex-col flex-1 min-h-0">
                <div className="bg-gray-800 px-3 py-1.5 flex items-center text-xs text-gray-400 border-b border-gray-700 flex-shrink-0">
                  <Terminal className="w-3 h-3 mr-2" /> Live Processing Log
                </div>
                <div className="p-3 overflow-y-auto flex-1 font-mono text-xs text-gray-300 space-y-1">
                  {progress.logs && progress.logs.map((log, i) => (
                    <div key={i} className={log.includes('ERROR') ? 'text-red-400' : log.includes('SUCCESS') ? 'text-green-400' : ''}>
                      {log}
                    </div>
                  ))}
                  <div ref={logsEndRef} />
                </div>
              </div>
            </div>
          ) : step === 2 ? (
            // SCAN RESULTS (DONE + CONFLICTS TABS)
            <div className="flex flex-col h-full">
              <div className="px-4 py-2 border-b border-gray-100 bg-gray-50 flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => setResultTab("ready")}
                  className={"px-3 py-1.5 rounded-md text-xs font-semibold inline-flex items-center transition-colors " + (resultTab === "ready" ? "bg-blue-600 text-white shadow-sm" : "bg-white text-gray-600 border border-gray-300 hover:bg-gray-100")}
                >
                  <FolderSearch className="w-3.5 h-3.5 mr-1.5" />
                  Ready ({scanData ? scanData.total_pending : 0})
                </button>
                <button
                  onClick={() => setResultTab("conflicts")}
                  className={"px-3 py-1.5 rounded-md text-xs font-semibold inline-flex items-center transition-colors " + (resultTab === "conflicts" ? "bg-red-600 text-white shadow-sm" : "bg-white text-gray-600 border border-gray-300 hover:bg-gray-100")}
                >
                  <AlertTriangle className="w-3.5 h-3.5 mr-1.5" />
                  Conflicts ({scanData ? scanData.total_conflicts : 0})
                </button>
                <button
                  onClick={() => setResultTab("done")}
                  className={"px-3 py-1.5 rounded-md text-xs font-semibold inline-flex items-center transition-colors " + (resultTab === "done" ? "bg-emerald-600 text-white shadow-sm" : "bg-white text-gray-600 border border-gray-300 hover:bg-gray-100")}
                >
                  <FolderOpen className="w-3.5 h-3.5 mr-1.5" />
                  Done ({scanData ? scanData.total_done : 0})
                </button>
                <button
                  onClick={exportCSV}
                  disabled={!scanData}
                  className="ml-auto px-3 py-1.5 rounded-md text-xs font-semibold inline-flex items-center transition-colors bg-white text-gray-700 border border-gray-300 hover:bg-gray-100 disabled:opacity-50 shadow-sm"
                >
                  <Download className="w-3.5 h-3.5 mr-1.5" />
                  Export CSV
                </button>
                {resultTab === "conflicts" && scanData && scanData.total_conflicts > 0 && (
                  <button
                    onClick={dismissAllConflicts}
                    className="px-3 py-1.5 rounded-md text-xs font-semibold inline-flex items-center transition-colors bg-white text-red-600 border border-red-200 hover:bg-red-50 shadow-sm"
                  >
                    <X className="w-3.5 h-3.5 mr-1.5" />
                    Dismiss all
                  </button>
                )}
              </div>
              <div className="flex-1 overflow-y-auto p-0">
                {resultTab === "ready" ? (
                  scanData && scanData.pending_folders && scanData.pending_folders.length > 0 ? (
                    <>
                      {scanData.total_pending > scanData.pending_folders.length && (
                        <div className="px-4 py-2 text-[11px] text-amber-700 bg-amber-50 border-b border-amber-100">
                          Showing first {scanData.pending_folders.length} of {scanData.total_pending} ready folders. Fix conflicts, then re-scan.
                        </div>
                      )}
                      <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-white sticky top-0 shadow-sm">
                          <tr>
                            <th className="px-4 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider bg-gray-50">Folder / Request</th>
                            <th className="px-4 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider bg-gray-50">Status</th>
                          </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-100">
                          {scanData.pending_folders.map((folder, idx) => (
                            <tr key={idx} className="hover:bg-gray-50 transition-colors">
                              <td className="px-4 py-2 text-xs font-medium text-gray-800 border-r border-gray-50 w-1/2">{folder}</td>
                              <td className="px-4 py-2 text-xs w-1/2">
                                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-100 text-emerald-700">
                                  <CheckCircle className="w-3 h-3 mr-1" /> Ready
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  ) : scanData ? (
                    <div className="flex flex-col items-center justify-center h-full text-gray-400">
                      <CheckCircle className="w-12 h-12 mb-2 text-gray-300" />
                      <p className="text-sm">No ready folders. Resolve conflicts or check the input directory.</p>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center h-full text-gray-400">
                      <FolderSearch className="w-12 h-12 mb-2 text-gray-300" />
                      <p className="text-sm">Click Scan to view directory contents.</p>
                    </div>
                  )
                ) : resultTab === "done" ? (
                  scanData && scanData.done_folders && scanData.done_folders.length > 0 ? (
                    <>
                      {scanData.total_done > scanData.done_folders.length && (
                        <div className="px-4 py-2 text-[11px] text-amber-700 bg-amber-50 border-b border-amber-100">
                          Showing first {scanData.done_folders.length} of {scanData.total_done} archived folders.
                        </div>
                      )}
                      <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-white sticky top-0 shadow-sm">
                          <tr>
                            <th className="px-4 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider bg-gray-50">Folder / Request</th>
                            <th className="px-4 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider bg-gray-50">Status</th>
                          </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-100">
                          {scanData.done_folders.map((folder, idx) => (
                            <tr key={idx} className="hover:bg-gray-50 transition-colors">
                              <td className="px-4 py-2 text-xs font-medium text-gray-800 border-r border-gray-50 w-1/2">{folder}</td>
                              <td className="px-4 py-2 text-xs w-1/2">
                                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-200 text-slate-700">
                                  <Archive className="w-3 h-3 mr-1" /> Archived
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  ) : scanData ? (
                    <div className="flex flex-col items-center justify-center h-full text-gray-400">
                      <CheckCircle className="w-12 h-12 mb-2 text-gray-300" />
                      <p className="text-sm">No archived folders in the Done directory yet.</p>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center h-full text-gray-400">
                      <FolderSearch className="w-12 h-12 mb-2 text-gray-300" />
                      <p className="text-sm">Click Scan to view directory contents.</p>
                    </div>
                  )
                ) : (
                scanData && scanData.conflicts && scanData.conflicts.length > 0 ? (
                  <div className="divide-y divide-gray-200">
                    {groupConflicts(scanData.conflicts).map((g, gi) => {
                      const open = expandedGroups[g.reason] ?? gi === 0;
                      return (
                        <div key={gi}>
                          <div className="flex items-center gap-2 px-4 py-2.5 bg-gray-50 hover:bg-gray-100 cursor-pointer select-none" onClick={() => toggleGroup(g.reason)}>
                            {open ? <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-gray-500 flex-shrink-0" />}
                            <span className="text-xs font-semibold text-gray-800 flex-1 break-words">{g.reason}</span>
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold bg-red-100 text-red-700 flex-shrink-0">{g.items.length}</span>
                            {bulkReplace && bulkReplace.reason === g.reason && (
                              <span className="text-[11px] font-semibold text-blue-600 flex-shrink-0">Replacing {bulkReplace.done}/{bulkReplace.total}...</span>
                            )}
                            {g.reason.startsWith("Duplicate Request Number") && (
                              <button
                                onClick={(e) => { e.stopPropagation(); replaceAllDuplicates(g); }}
                                disabled={bulkReplace != null}
                                title="Replace database rows for all folders in this group"
                                className="px-2 py-1 rounded text-[11px] font-semibold bg-white text-blue-600 border border-blue-200 hover:bg-blue-50 disabled:opacity-50 flex-shrink-0 inline-flex items-center"
                              >
                                <RefreshCw className="w-3 h-3 mr-1" /> Replace all
                              </button>
                            )}
                            <button
                              onClick={(e) => { e.stopPropagation(); dismissGroup(g.reason, g.items.length); }}
                              title="Dismiss this whole problem group"
                              className="px-2 py-1 rounded text-[11px] font-semibold bg-white text-gray-600 border border-gray-300 hover:bg-gray-200 flex-shrink-0 inline-flex items-center"
                            >
                              <X className="w-3 h-3 mr-1" /> Dismiss
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); deleteGroupFolders(g.items); }}
                              title="Delete all input folders in this group"
                              className="px-2 py-1 rounded text-[11px] font-semibold bg-white text-red-600 border border-red-200 hover:bg-red-50 flex-shrink-0 inline-flex items-center"
                            >
                              <Trash2 className="w-3 h-3 mr-1" /> Folders
                            </button>
                          </div>
                          {open && (
                            <table className="min-w-full divide-y divide-gray-100">
                              <tbody className="bg-white divide-y divide-gray-100">
                                {g.items.map((conflict, idx) => (
                                  <tr key={idx} className="hover:bg-gray-50 transition-colors">
                                    <td className="pl-10 pr-4 py-2 text-xs font-medium text-gray-800">{conflict.folder}</td>
                                    <td className="px-4 py-2 text-right whitespace-nowrap w-24">
                                      {g.reason.startsWith("Duplicate Request Number") && (
                                        <button
                                          onClick={() => replaceDuplicate(conflict)}
                                          disabled={bulkReplace != null}
                                          title="Replace database rows with this folder's files"
                                          className="p-1.5 rounded text-blue-600 hover:bg-blue-100 hover:text-blue-800 mr-1 disabled:opacity-50"
                                        >
                                          <RefreshCw className="w-3.5 h-3.5" />
                                        </button>
                                      )}
                                      <button
                                        onClick={() => dismissConflict(conflict)}
                                        title="Dismiss this conflict"
                                        className="p-1.5 rounded text-gray-500 hover:bg-gray-200 hover:text-gray-700 mr-1"
                                      >
                                        <X className="w-3.5 h-3.5" />
                                      </button>
                                      <button
                                        onClick={() => deleteFolder(conflict.folder)}
                                        title="Delete this input folder permanently"
                                        className="p-1.5 rounded text-red-500 hover:bg-red-100 hover:text-red-700"
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                      </button>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : scanData ? (
                  <div className="flex flex-col items-center justify-center h-full text-gray-400">
                    <CheckCircle className="w-12 h-12 mb-2 text-gray-300" />
                    <p className="text-sm">No conflicts found. Ready to process {scanData.total_pending} folders.</p>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center h-full text-gray-400">
                    <FolderSearch className="w-12 h-12 mb-2 text-gray-300" />
                    <p className="text-sm">Click Scan to view directory contents.</p>
                  </div>
                ))}
              </div>
              <div className="px-4 py-2.5 border-t border-gray-100 bg-gray-50 flex justify-between items-center flex-shrink-0">
                <button onClick={() => setStep(1)} className="px-4 py-2 bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 rounded-md text-sm font-medium transition-colors shadow-sm">
                  Back to paths
                </button>
                <div className="flex gap-2">
                  <button onClick={fetchScan} disabled={loading || running} className="px-4 py-2 bg-slate-200 text-slate-700 hover:bg-slate-300 rounded-md text-sm font-medium transition-colors inline-flex items-center shadow-sm disabled:opacity-50">
                    <RefreshCw className={"w-4 h-4 mr-2 " + (loading && !running ? "animate-spin" : "")} />
                    Re-scan
                  </button>
                  <button onClick={() => setStep(3)} disabled={running} className="px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-md text-sm font-medium transition-colors shadow-sm disabled:opacity-50">
                    Continue to run
                  </button>
                </div>
              </div>
            </div>
          ) : step === 1 ? (
            <div className="flex flex-col items-center justify-center h-full p-8 text-center text-gray-400">
              <FolderSearch className="w-12 h-12 mb-2 text-gray-300" />
              <p className="text-sm font-semibold text-gray-600">Step 2 preview</p>
              <p className="text-sm">Set your paths, click "Scan folders and continue", and the review lists will appear here.</p>
            </div>
          ) : step === 4 ? (
            <div className="flex flex-col h-full">
              <div className="px-4 py-2 border-b border-gray-100 bg-gray-50 flex items-center gap-2 flex-shrink-0">
                <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold">4</span>
                <span className="text-sm font-semibold text-gray-700">Migrate to map database (PostGIS)</span>
                <button onClick={fetchMigrate} disabled={migrating} className="ml-auto px-3 py-1.5 rounded-md text-xs font-semibold inline-flex items-center bg-white text-gray-600 border border-gray-300 hover:bg-gray-100 disabled:opacity-50 shadow-sm">
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Refresh
                </button>
                <button onClick={runMigrate} disabled={migrating || !pipelineRan || (migStatus && !migStatus.gpkg_exists)} title={!pipelineRan ? "Run the pipeline first (step 3)" : ""} className="px-3 py-1.5 rounded-md text-xs font-semibold inline-flex items-center bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 shadow-sm">
                  <Play className="w-3.5 h-3.5 mr-1.5" /> {migrating ? "Migrating..." : "Migrate now"}
                </button>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {!migStatus ? (
                  <p className="text-sm text-gray-400">Loading migration status...</p>
                ) : (
                  <>
                    {migStatus && !pipelineRan && (
                      <div className="p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-md text-sm">
                        Pipeline has not run yet in this session — go back to step 3 and run it first, then migrate the fresh results.
                      </div>
                    )}
                    {!migStatus.gpkg_exists && (
                      <div className="p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-md text-sm">
                        No processed database file yet — run the pipeline (step 3) first, then migrate.
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-4">
                      <div className="border border-gray-200 rounded-lg p-3">
                        <p className="text-[11px] font-bold text-gray-500 uppercase tracking-wider mb-2">File database (GPKG)</p>
                        {["Land", "Eshghalat", "Point"].map((l) => (
                          <div key={l} className="flex justify-between text-xs py-0.5">
                            <span className="text-gray-600">{l}</span>
                            <span className="font-bold text-gray-900">{migStatus.gpkg_layers && migStatus.gpkg_layers[l] != null ? migStatus.gpkg_layers[l] : 0}</span>
                          </div>
                        ))}
                      </div>
                      <div className="border border-gray-200 rounded-lg p-3">
                        <p className="text-[11px] font-bold text-gray-500 uppercase tracking-wider mb-2">Map database (PostGIS)</p>
                        {["land", "eshghalat", "point"].map((l) => (
                          <div key={l} className="flex justify-between text-xs py-0.5">
                            <span className="text-gray-600">{l}</span>
                            <span className="font-bold text-gray-900">{migStatus.postgis && migStatus.postgis[l] != null ? migStatus.postgis[l] : 0}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <p className="text-[11px] font-bold text-gray-500 uppercase tracking-wider mb-2">Migration history — who moved what</p>
                      {migHistory.length === 0 ? (
                        <p className="text-xs text-gray-400">No migrations recorded yet.</p>
                      ) : (
                        <table className="min-w-full divide-y divide-gray-200">
                          <thead className="bg-gray-50">
                            <tr>
                              <th className="px-3 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider">Time</th>
                              <th className="px-3 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider">User</th>
                              <th className="px-3 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider">Table</th>
                              <th className="px-3 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider">Migrated</th>
                              <th className="px-3 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider">Skipped</th>
                            </tr>
                          </thead>
                          <tbody className="bg-white divide-y divide-gray-100">
                            {migHistory.map((h) => (
                              <tr key={h.id} className="hover:bg-gray-50">
                                <td className="px-3 py-2 text-xs text-gray-600">{h.created_at ? new Date(h.created_at).toLocaleString() : "-"}</td>
                                <td className="px-3 py-2 text-xs">
                                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-blue-100 text-blue-700">{h.username}</span>
                                </td>
                                <td className="px-3 py-2 text-xs font-medium text-gray-800">{h.table}</td>
                                <td className="px-3 py-2 text-xs font-bold text-emerald-600">+{h.migrated}</td>
                                <td className="px-3 py-2 text-xs text-gray-500">{h.skipped}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : null}
        </div>
      </div>
      {confirmModal}
    </div>
  );
};

export default DataProcessor;
