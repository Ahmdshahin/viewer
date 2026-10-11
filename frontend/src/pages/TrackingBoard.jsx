import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { RefreshCw, Loader2, Building2, MapPinned } from "lucide-react";
import { useNavigate } from "react-router-dom";

const H = () => (localStorage.getItem("token") ? { Authorization: "Bearer " + localStorage.getItem("token") } : {});

// Both ledgers are full mirrors of the same record, so one board renders either.
// Only the API prefix, the heading and the page a card links to differ.
const LEDGERS = {
  company: { base: "/api/v1/requests", label: "Company Requests", page: "/requests", Icon: Building2, perm: "requests" },
  mudryia: { base: "/api/v1/mudryia-requests", label: "Mudryia Requests", page: "/mudryia-requests", Icon: MapPinned, perm: "mudryia_requests" },
};

const COLUMN_TONES = {
  "مقبول": "bg-emerald-50 border-emerald-300",
  "مرفوض": "bg-red-50 border-red-300",
  "قيد المعاينة": "bg-amber-50 border-amber-300",
  "بالمراجعة الفنية": "bg-blue-50 border-blue-300",
  "تم الارسال": "bg-cyan-50 border-cyan-300",
  "تم الرفع ع المنظومة": "bg-teal-50 border-teal-300",
  "لم يتم الرفع ع المنظومة": "bg-orange-50 border-orange-300",
  "جاري العمل عليه": "bg-indigo-50 border-indigo-300",
  "جديد": "bg-slate-100 border-slate-300",
  "لم يتم العمل عليه": "bg-fuchsia-50 border-fuchsia-300",
  "مكتمل ولم يرسل": "bg-lime-50 border-lime-300",
};
const PILL = {
  "مقبول": "bg-emerald-500",
  "مرفوض": "bg-red-500",
  "قيد المعاينة": "bg-amber-500",
  "بالمراجعة الفنية": "bg-blue-500",
  "تم الارسال": "bg-cyan-500",
  "تم الرفع ع المنظومة": "bg-teal-500",
  "لم يتم الرفع ع المنظومة": "bg-orange-500",
  "جاري العمل عليه": "bg-indigo-500",
  "جديد": "bg-slate-400",
  "لم يتم العمل عليه": "bg-fuchsia-500",
  "مكتمل ولم يرسل": "bg-lime-500",
};

export default function TrackingBoard() {
  const [ledgerKey, setLedgerKey] = useState("company");
  const [allowed, setAllowed] = useState({ company: true, mudryia: true });
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const ledger = LEDGERS[ledgerKey];
  const PER_PAGE = 300;

  // Only offer a ledger the signed-in user may actually open.
  useEffect(() => {
    let cancelled = false;
    axios.get("/api/v1/auth/me", { headers: H() })
      .then((res) => {
        if (cancelled) return;
        const perms = res.data.permissions || [];
        setAllowed({ company: perms.includes("requests"), mudryia: perms.includes("mudryia_requests") });
      })
      .catch(() => { /* keep both visible; the API will reject if not allowed */ });
    return () => { cancelled = true; };
  }, []);

  // No fallback effect needed: the ledger buttons are disabled unless the user
  // holds that ledger's permission, so an impermissible ledger can't be selected.
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await axios.get(ledger.base, { headers: H(), params: { per_page: PER_PAGE } });
      setItems(res.data.items);
      setTotal(res.data.total);
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [ledger.base]);

  useEffect(() => { load(); }, [load]);

  const grouped = {};
  items.forEach((r) => {
    const s = r.request_status || "autre";
    if (!grouped[s]) grouped[s] = [];
    grouped[s].push(r);
  });
  const order = ["جديد", "قيد المعاينة", "بالمراجعة الفنية", "تم الارسال", "تم الرفع ع المنظومة",
    "لم يتم الرفع ع المنظومة", "جاري العمل عليه", "مكتمل ولم يرسل", "مقبول", "مرفوض", "لم يتم العمل عليه"];
  const statuses = [...order.filter((s) => grouped[s]), ...Object.keys(grouped).filter((s) => !order.includes(s))];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="p-6 pb-3 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Tracking board</h1>
          <p className="text-sm text-gray-500 mt-1">Workflow positions of the {ledger.label} team</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1 bg-white border border-gray-200 rounded-lg p-1">
            {Object.entries(LEDGERS).map(([k, L]) => {
              const Icon = L.Icon;
              const disabled = allowed[k] === false;
              return (
                <button key={k} onClick={() => setLedgerKey(k)} disabled={disabled}
                  title={disabled ? `You do not have the ${L.label} permission` : L.label}
                  className={"px-3 py-1.5 rounded-md text-xs font-semibold inline-flex items-center gap-1.5 " +
                    (k === ledgerKey ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100") +
                    (disabled ? " opacity-40 cursor-not-allowed" : "")}>
                  <Icon className="w-3.5 h-3.5" /> {L.label}
                </button>
              );
            })}
          </div>
          <button onClick={load} disabled={loading}
            className="inline-flex items-center px-3 py-2 rounded-md text-xs font-semibold bg-slate-900 text-white hover:bg-slate-700 disabled:opacity-50">
            <RefreshCw className={"w-3.5 h-3.5 mr-1.5 " + (loading ? "animate-spin" : "")} /> Refresh
          </button>
        </div>
      </div>

      {error && <p className="px-6 text-sm text-red-600">{error}</p>}

      {!loading && total > items.length && (
        <p className="px-6 pb-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-1.5 inline-block">
          Showing the {items.length} most recent of {total.toLocaleString("en-US")} requests in this ledger.
          Narrow it down with the filters on the <button className="underline font-semibold" onClick={() => navigate(ledger.page)}>{ledger.label}</button> page.
        </p>
      )}

      <div className="flex-1 overflow-x-auto px-6 pb-6">
        <div className="flex gap-4 h-full items-start min-w-max">
          {statuses.map((s) => (
            <div key={s} className={"w-72 shrink-0 rounded-xl border p-3 flex flex-col " + (COLUMN_TONES[s] || "bg-gray-50 border-gray-200")}>
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-bold text-slate-700 flex items-center gap-2">
                  <span className={"w-2.5 h-2.5 rounded-full " + (PILL[s] || "bg-gray-400")} />
                  {s || "—"}
                </span>
                <span className="text-xs font-semibold text-slate-500 bg-white/70 rounded-full px-2 py-0.5">
                  {(grouped[s] || []).length}
                </span>
              </div>
              <div className="space-y-2 overflow-y-auto">
                {(grouped[s] || []).slice(0, 60).map((r) => (
                  <button key={r.id} onClick={() => navigate(ledger.page)}
                    className="w-full text-left bg-white rounded-lg shadow-sm border border-gray-100 p-3 hover:border-blue-200 hover:shadow transition"
                    onDoubleClick={() => navigate(ledger.page)}>
                    <p className="font-mono text-[11px] text-blue-700 break-all">{r.req_number}</p>
                    <p className="text-sm text-slate-700 mt-1 truncate">{r.applicant || "—"}</p>
                    <p className="text-[11px] text-gray-400 mt-0.5 truncate">
                      {[r.center, r.surveyor, r.area_value ? `${r.area_value} ${r.area_unit || ""}` : ""].filter(Boolean).join(" • ")}
                    </p>
                  </button>
                ))}
                {(grouped[s] || []).length > 60 && (
                  <p className="text-center text-[11px] text-gray-400">+{(grouped[s] || []).length - 60} more</p>
                )}
                {!(grouped[s] || []).length && <p className="text-center text-xs text-gray-400 py-4">Empty</p>}
              </div>
            </div>
          ))}
          {loading && !items.length && (
            <div className="flex items-center justify-center w-full h-40 text-gray-400">
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading…
            </div>
          )}
        </div>
      </div>
    </div>
  );
}