import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Plus, RefreshCw, Power, CheckCircle2, Pencil, Save, X, GitMerge, Trash2 } from "lucide-react";

const H = () => (localStorage.getItem("token") ? { Authorization: "Bearer " + localStorage.getItem("token") } : {});

const KINDS = [
  { key: "governorates", label: "Governorates" },
  { key: "centers", label: "Centers" },
  { key: "villages", label: "Villages" },
  { key: "area_units", label: "Area units" },
  { key: "request_status", label: "Request statuses", values: true },
  { key: "survey_status", label: "Survey statuses", values: true },
  { key: "raw_status", label: "Raw statuses", values: true },
  { key: "surveyor", label: "Surveyors", values: true },
  { key: "office", label: "Offices", values: true },
];

export default function LookupsAdmin() {
  const [kind, setKind] = useState("governorates");
  const [items, setItems] = useState([]);
  const [govs, setGovs] = useState([]);
  const [centers, setCenters] = useState([]);
  const [govFilter, setGovFilter] = useState("");
  const [centerFilter, setCenterFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [adding, setAdding] = useState(false);
  const [addForm, setAddForm] = useState({ name: "", code: "" });
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({ name: "", code: "" });
  const [mergeSel, setMergeSel] = useState({});
  const [mergeTarget, setMergeTarget] = useState("");
  const [mergeBusy, setMergeBusy] = useState(false);

  const isValueKind = ["request_status", "survey_status", "raw_status", "surveyor", "office"].includes(kind);
  const noCode = isValueKind || kind === "villages";

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (isValueKind) {
        const res = await axios.get(`/api/v1/lookups/values/${kind}`, {
          headers: H(), params: { include_inactive: true },
        });
        setItems(res.data);
      } else {
        const params = {};
        if (kind === "centers" && govFilter) params.governorate_id = govFilter;
        if (kind === "villages" && centerFilter) params.center_id = centerFilter;
        const res = await axios.get(`/api/v1/lookups/${kind}`, { headers: H(), params });
        setItems(res.data);
      }
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [kind, govFilter, centerFilter, isValueKind]);

  const loadHelpers = useCallback(async () => {
    try {
      const [g, c] = await Promise.all([
        axios.get("/api/v1/lookups/governorates", { headers: H() }),
        axios.get("/api/v1/lookups/centers", { headers: H(), params: { include_inactive: true } }),
      ]);
      setGovs(g.data);
      setCenters(c.data);
    } catch (e) { /* ignore */ }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadHelpers(); }, [loadHelpers]);

  const switchKind = (k) => {
    setKind(k);
    setGovFilter("");
    setCenterFilter("");
    setAdding(false);
    setEditingId(null);
    setMergeSel({});
    setMergeTarget("");
  };

  const add = async () => {
    setError("");
    setNote("");
    try {
      if (isValueKind) {
        await axios.post(`/api/v1/lookups/values/${kind}`, { name: addForm.name.trim() }, { headers: H() });
      } else {
        const body = { name: addForm.name.trim(), code: addForm.code.trim() || undefined };
        if (kind === "centers") body.governorate_id = Number(govFilter);
        if (kind === "villages") body.center_id = Number(centerFilter);
        if (kind === "area_units") body.code = addForm.code.trim();
        await axios.post(`/api/v1/lookups/${kind}`, body, { headers: H() });
      }
      const created = addForm.name.trim();
      setNote(`Added "${created}"`);
      setAddForm({ name: "", code: "" });
      setAdding(false);
      load();
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to add");
    }
  };

  const startEdit = (it) => {
    setEditingId(it.id);
    setEditForm({ name: it.name || "", code: it.code || "" });
    setNote("");
    setError("");
  };

  const saveEdit = async () => {
    try {
      const body = isValueKind ? { name: editForm.name } : editForm;
      const url = isValueKind
        ? `/api/v1/lookups/values/${kind}/${editingId}`
        : `/api/v1/lookups/${kind}/${editingId}`;
      const res = await axios.patch(url, body, { headers: H() });
      const extra = res.data && res.data.rows_updated ? ` — ${res.data.rows_updated} ledger row(s) updated` : "";
      setNote("Saved" + extra);
      setEditingId(null);
      load();
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to update");
    }
  };

  const toggleActive = async (it) => {
    try {
      const base = isValueKind ? `/api/v1/lookups/values/${kind}` : `/api/v1/lookups/${kind}`;
      await axios.post(`${base}/${it.id}/${it.is_active ? "disable" : "enable"}`, {}, { headers: H() });
      load();
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to toggle");
    }
  };

  const deleteValue = async (it) => {
    if (!window.confirm(`Delete "${it.name}" permanently? Only possible when no request uses it.`)) return;
    setError("");
    setNote("");
    try {
      await axios.delete(`/api/v1/lookups/values/${kind}/${it.id}`, { headers: H() });
      setNote(`Deleted "${it.name}"`);
      load();
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to delete");
    }
  };

  const mergeIds = Object.keys(mergeSel).filter((k) => mergeSel[k]).map(Number);

  const doMerge = async () => {
    if (!mergeIds.length || !mergeTarget || mergeBusy) return;
    const target = items.find((i) => String(i.id) === String(mergeTarget));
    if (!window.confirm(`Merge ${mergeIds.length} row(s) into "${target ? target.name : mergeTarget}"? Requests will be re-pointed and sources disabled.`)) return;
    setMergeBusy(true);
    setError("");
    setNote("");
    try {
      const url = isValueKind ? `/api/v1/lookups/values/${kind}/merge` : `/api/v1/lookups/${kind}/merge`;
      const res = await axios.post(url, { source_ids: mergeIds, target_id: Number(mergeTarget) }, { headers: H() });
      setNote(`Merged — ${res.data.moved} request reference(s) re-pointed`);
      setMergeSel({});
      setMergeTarget("");
      load();
      loadHelpers();
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to merge");
    } finally {
      setMergeBusy(false);
    }
  };

  const subTitle = kind === "centers" ? "Parent governorate" : kind === "villages" ? "Parent center" : null;
  const kindNoun = isValueKind ? "value" : kind.replace("_", " ");

  return (
    <div className="p-8 overflow-y-auto h-full">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Lookup tables</h1>
          <p className="text-sm text-gray-500 mt-1">Divisions, units, request vocabularies and staff lists</p>
        </div>
        <button onClick={load} disabled={loading}
          className="inline-flex items-center px-3 py-2 rounded-md text-xs font-semibold bg-slate-900 text-white hover:bg-slate-700 disabled:opacity-50">
          <RefreshCw className={"w-3.5 h-3.5 mr-1.5 " + (loading ? "animate-spin" : "")} /> Refresh
        </button>
      </div>

      {/* Kind tabs */}
      <div className="flex gap-2 mb-5 flex-wrap">
        {KINDS.map((k) => (
          <button key={k.key} onClick={() => switchKind(k.key)}
            className={"px-4 py-2 rounded-md text-sm font-semibold " +
              (kind === k.key ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100")}>
            {k.label}
          </button>
        ))}
      </div>

      {/* Parent filters */}
      {subTitle && !isValueKind && (
        <div className="mb-4">
          <label className="text-xs uppercase tracking-wider text-gray-400 mr-2">{subTitle}</label>
          {kind === "centers" ? (
            <select value={govFilter} onChange={(e) => setGovFilter(e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200">
              <option value="">All governorates</option>
              {govs.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          ) : (
            <select value={centerFilter} onChange={(e) => setCenterFilter(e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200">
              <option value="">All centers</option>
              {centers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
        </div>
      )}

      {/* Merge bar */}
      {mergeIds.length > 0 && (
        <div className="mb-3 flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <GitMerge className="w-4 h-4 text-amber-600" />
          <span className="text-xs font-semibold text-amber-800">{mergeIds.length} selected to merge</span>
          <select value={mergeTarget} onChange={(e) => setMergeTarget(e.target.value)}
            className="px-2 py-1.5 text-xs rounded-md border border-amber-300 bg-white min-w-[200px]">
            <option value="">Merge into...</option>
            {items.filter((i) => !mergeSel[i.id]).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
          <button onClick={doMerge} disabled={!mergeTarget || mergeBusy}
            className="px-3 py-1.5 rounded-md text-xs font-semibold bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-40">
            {mergeBusy ? "Merging..." : "Merge"}
          </button>
          <button onClick={() => { setMergeSel({}); setMergeTarget(""); }} className="text-xs text-amber-700 hover:underline">Clear</button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-slate-500 text-xs uppercase tracking-wider">
            <tr>
              <th className="px-4 py-2 w-8"></th>
              <th className="text-left px-4 py-2 font-semibold">Name</th>
              {!noCode && <th className="text-left px-4 py-2 font-semibold">Code</th>}
              <th className="text-left px-4 py-2 font-semibold">Status</th>
              <th className="text-right px-4 py-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id} className={"border-b border-gray-100" + (mergeSel[it.id] ? " bg-amber-50" : "")}>
                <td className="px-4 py-2">
                  <input type="checkbox" checked={!!mergeSel[it.id]} onChange={() => setMergeSel((s) => ({ ...s, [it.id]: !s[it.id] }))} className="accent-amber-600" title="Select for merge" />
                </td>
                <td className="px-4 py-2 text-slate-700">
                  {editingId === it.id ? (
                    <input value={editForm.name} onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                      className="px-2 py-1 text-sm rounded-md border border-gray-200" />
                  ) : it.name}
                </td>
                {!noCode && (
                  <td className="px-4 py-2 font-mono text-xs text-slate-500">
                    {editingId === it.id ? (
                      <input value={editForm.code || ""} onChange={(e) => setEditForm((f) => ({ ...f, code: e.target.value }))}
                        className="px-2 py-1 text-sm rounded-md border border-gray-200 w-24" />
                    ) : (it.code || "—")}
                  </td>
                )}
                <td className="px-4 py-2">
                  <span className={"text-[11px] font-semibold border rounded px-1.5 py-0.5 " +
                    (it.is_active ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-gray-100 text-gray-400 border-gray-200")}>
                    {it.is_active ? "Active" : "Disabled"}
                  </span>
                </td>
                <td className="px-4 py-2 text-right whitespace-nowrap">
                  {editingId === it.id ? (
                    <>
                      <button onClick={saveEdit} className="inline-flex items-center text-emerald-600 hover:text-emerald-700 mr-2">
                        <Save className="w-4 h-4" />
                      </button>
                      <button onClick={() => setEditingId(null)} className="text-gray-400 hover:text-gray-600">
                        <X className="w-4 h-4" />
                      </button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => startEdit(it)} className="text-gray-500 hover:text-blue-600 mr-3" title="Edit">
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button onClick={() => toggleActive(it)}
                        className={it.is_active ? "text-gray-400 hover:text-red-600" : "text-emerald-600 hover:text-emerald-700"}
                        title={it.is_active ? "Disable" : "Enable"}>
                        {it.is_active ? <Power className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
                      </button>
                      {isValueKind && !it.is_active && (
                        <button onClick={() => deleteValue(it)}
                          className="text-gray-400 hover:text-red-600 ml-3" title="Delete permanently">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-10 text-center text-gray-400 text-sm">Nothing here yet</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
