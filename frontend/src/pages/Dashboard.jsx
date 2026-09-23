import { useEffect, useState } from "react";
import axios from "axios";
import { RefreshCw, Users, Shield, ShieldCheck, UserCog, Eye, CheckCircle2, XCircle, Layers as LayersIcon } from "lucide-react";

const LAYERS = [
  { table: "lands", label: "Land Parcels", color: "#e74c3c", hasArea: true },
  { table: "eshghalat", label: "Eshghalat", color: "#3498db", hasArea: true },
  { table: "points", label: "Survey Points", color: "#27ae60", hasArea: false },
  { table: "mudryia", label: "Mudryia", color: "#8e44ad", hasArea: false },
];

const fmt = (n, d = 0) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d }));

export default function Dashboard() {
  const [stats, setStats] = useState({});
  const [users, setUsers] = useState(null);
  const [usersDenied, setUsersDenied] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const token = localStorage.getItem("token");
    const headers = token ? { Authorization: "Bearer " + token } : {};
    try {
      const results = await Promise.all(LAYERS.map((l) => axios.get(`/api/v1/layers/${l.table}/stats`, { headers })));
      setStats(Object.fromEntries(LAYERS.map((l, i) => [l.table, results[i].data])));
    } catch (err) {
      console.error("Failed to load layer stats", err);
    }
    try {
      const res = await axios.get("/api/v1/users", { headers });
      setUsers(res.data);
      setUsersDenied(false);
    } catch (err) {
      setUsers(null);
      setUsersDenied(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalFeatures = LAYERS.reduce((acc, l) => acc + ((stats[l.table] || {}).count || 0), 0);
  const totalAreaFeddan = LAYERS.reduce((acc, l) => acc + ((stats[l.table] || {}).total_area_feddan || 0), 0);

  const userCounts = {
    total: (users || []).length,
    active: (users || []).filter((u) => u.is_active).length,
    admin: (users || []).filter((u) => u.role === "admin").length,
    editor: (users || []).filter((u) => u.role === "editor").length,
    viewer: (users || []).filter((u) => u.role === "viewer").length,
  };

  const roleBadge = (role) =>
    role === "admin"
      ? "bg-red-50 text-red-700 border-red-200"
      : role === "editor"
      ? "bg-blue-50 text-blue-700 border-blue-200"
      : "bg-gray-50 text-gray-600 border-gray-200";

  const roleIcon = (role) =>
    role === "admin" ? <Shield className="w-3 h-3 mr-1" />
    : role === "editor" ? <UserCog className="w-3 h-3 mr-1" />
    : <Eye className="w-3 h-3 mr-1" />;

  return (
    <div className="p-8 overflow-y-auto h-full">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">Live statistics from the spatial database</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center px-3 py-2 rounded-md text-xs font-semibold bg-slate-900 text-white hover:bg-slate-700 disabled:opacity-50"
        >
          <RefreshCw className={"w-3.5 h-3.5 mr-1.5 " + (loading ? "animate-spin" : "")} /> Refresh
        </button>
      </div>

      {/* Layer summary strip */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="bg-white p-5 rounded shadow border-l-4 border-slate-800">
          <p className="text-gray-500 text-sm uppercase tracking-wider">Total features</p>
          <p className="text-3xl font-bold mt-1 text-slate-800">{fmt(totalFeatures)}</p>
        </div>
        <div className="bg-white p-5 rounded shadow border-l-4 border-slate-800">
          <p className="text-gray-500 text-sm uppercase tracking-wider">Combined area (feddan)</p>
          <p className="text-3xl font-bold mt-1 text-slate-800">{fmt(totalAreaFeddan, 2)}</p>
        </div>
      </div>

      {/* Per-layer cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        {LAYERS.map((l) => {
          const st = stats[l.table] || {};
          return (
            <div key={l.table} className="bg-white p-6 rounded shadow" style={{ borderTop: "4px solid " + l.color }}>
              <div className="flex items-center justify-between">
                <h2 className="text-gray-500 text-sm uppercase tracking-wider flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full" style={{ backgroundColor: l.color }} />
                  {l.label}
                </h2>
                <LayersIcon className="w-4 h-4 text-gray-300" />
              </div>
              <p className="text-4xl font-bold mt-3 text-slate-800">
                {loading ? "…" : fmt(st.count)}
              </p>
              {l.hasArea && (
                <div className="mt-3 text-xs text-gray-500 space-y-0.5">
                  <p>{fmt(st.total_area_sqm)} m²</p>
                  <p className="font-semibold text-gray-600">{fmt(st.total_area_feddan, 2)} feddan</p>
                </div>
              )}
              {!l.hasArea && <p className="mt-3 text-xs text-gray-400">Point features — no area</p>}
            </div>
          );
        })}
      </div>

      {/* Users section */}
      <div className="bg-white rounded shadow mb-6">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-xl font-bold text-slate-800 flex items-center">
            <Users className="w-5 h-5 mr-2 text-slate-400" /> User Accounts
          </h2>
          {usersDenied && !loading && (
            <span className="text-[11px] text-gray-400 bg-gray-100 rounded px-2 py-1">Visible to administrators only</span>
          )}
        </div>

        {!usersDenied && users && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 px-6 py-5">
              <div className="rounded-lg bg-slate-50 p-4">
                <p className="text-[11px] uppercase tracking-wider text-gray-400 font-semibold">Total</p>
                <p className="text-2xl font-bold text-slate-800">{fmt(userCounts.total)}</p>
              </div>
              <div className="rounded-lg bg-green-50 p-4">
                <p className="text-[11px] uppercase tracking-wider text-green-600 font-semibold">Active</p>
                <p className="text-2xl font-bold text-green-700">{fmt(userCounts.active)}</p>
              </div>
              <div className="rounded-lg bg-red-50 p-4">
                <p className="text-[11px] uppercase tracking-wider text-red-500 font-semibold">Admins</p>
                <p className="text-2xl font-bold text-red-600">{fmt(userCounts.admin)}</p>
              </div>
              <div className="rounded-lg bg-blue-50 p-4">
                <p className="text-[11px] uppercase tracking-wider text-blue-500 font-semibold">Editors</p>
                <p className="text-2xl font-bold text-blue-600">{fmt(userCounts.editor)}</p>
              </div>
              <div className="rounded-lg bg-gray-100 p-4">
                <p className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Viewers</p>
                <p className="text-2xl font-bold text-gray-700">{fmt(userCounts.viewer)}</p>
              </div>
            </div>

            <div className="overflow-x-auto border-t border-gray-100">
              <table className="min-w-full divide-y divide-gray-100 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="text-left px-6 py-3 text-[11px] uppercase tracking-wider text-gray-400 font-semibold">Username</th>
                    <th className="text-left px-6 py-3 text-[11px] uppercase tracking-wider text-gray-400 font-semibold">Full name</th>
                    <th className="text-left px-6 py-3 text-[11px] uppercase tracking-wider text-gray-400 font-semibold">Role</th>
                    <th className="text-left px-6 py-3 text-[11px] uppercase tracking-wider text-gray-400 font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {(users || []).map((u) => (
                    <tr key={u.id} className="hover:bg-gray-50">
                      <td className="px-6 py-3 font-mono text-xs text-gray-800">{u.username}</td>
                      <td className="px-6 py-3 text-gray-600">{u.full_name || "—"}</td>
                      <td className="px-6 py-3">
                        <span className={"inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border " + roleBadge(u.role)}>
                          {roleIcon(u.role)} {u.role}
                        </span>
                      </td>
                      <td className="px-6 py-3">
                        {u.is_active
                          ? <span className="inline-flex items-center text-green-600 text-xs font-semibold"><CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Active</span>
                          : <span className="inline-flex items-center text-gray-400 text-xs font-semibold"><XCircle className="w-3.5 h-3.5 mr-1" /> Inactive</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {!usersDenied && !users && !loading && (
          <p className="px-6 py-5 text-sm text-gray-400">No user data available.</p>
        )}
      </div>
    </div>
  );
}