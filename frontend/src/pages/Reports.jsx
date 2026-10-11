import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import {
  BarChart3, RefreshCw, Download, Printer, RotateCcw, Loader2, CalendarDays,
  Building2, MapPinned,
} from "lucide-react";

const H = () => (localStorage.getItem("token") ? { Authorization: "Bearer " + localStorage.getItem("token") } : {});

const SECTIONS = [
  { id: "gov", label: "المحافظات", reports: ["by_governorate"], icon: "🏛" },
  { id: "center", label: "المراكز", reports: ["by_center"] },
  { id: "status", label: "الحالة والرفع المساحي", reports: ["by_status", "by_survey"] },
  { id: "company", label: "الشركات", reports: ["by_company"] },
  { id: "perf", label: "المساحون والمكاتب", reports: ["by_surveyor", "by_office"] },
  { id: "daily", label: "التقرير اليومي", reports: ["daily"] },
  { id: "users", label: "نشاط المستخدمين", reports: ["users"] },
  { id: "coverage", label: "تغطية الهندسة", reports: ["geometry_coverage", "no_geometry"] },
  { id: "stalled", label: "المتوقفة", reports: ["stalled"] },
];

const REPORT_TITLES = {
  by_governorate: "ملخص حسب المحافظة",
  by_center: "ملخص حسب المركز",
  by_status: "الطلبات حسب الحالة",
  by_survey: "الطلبات حسب حالة الرفع المساحي",
  by_company: "ملخص حسب الشركة",
  by_surveyor: "أداء المساحين",
  by_office: "أداء المكاتب الفنية",
  daily: "التقرير اليومي",
  users: "نشاط المستخدمين",
  geometry_coverage: "تغطية الهندسة بالمحافظة",
  no_geometry: "طلبات بدون هندسة على الخريطة",
  stalled: "الطلبات المتوقفة (غير منتهية)",
};

const fmtNum = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-US"));
const fmtCell = (v, type) => {
  if (v === null || v === undefined || v === "") return "—";
  if (type === "bool") return v ? "نعم" : "لا";
  if (type === "int" || type === "float") return fmtNum(v);
  return v;
};

const EMPTY_FORM = {
  date_from: "", date_to: "", governorate_id: "", center_id: "",
  request_status: "", survey_status: "", company: "", surveyor: "", office: "",
};

export default function Reports() {
  const [section, setSection] = useState("gov");
  const [ledger, setLedger] = useState("company");
  const [meta, setMeta] = useState(null);
  const [data, setData] = useState({});
  const [loading, setLoading] = useState({});
  const [error, setError] = useState("");

  const [form, setForm] = useState(EMPTY_FORM);
  const [applied, setApplied] = useState({});

  // Filter options (statuses, companies, date range) come from the ledger being
  // reported on, so they reload when the ledger changes. The stale state is
  // cleared in the click handler rather than here, to avoid a synchronous
  // setState cascade in the effect body.
  useEffect(() => {
    let cancelled = false;
    axios.get("/api/v1/reports/filters", { headers: H(), params: { ledger } })
      .then((res) => { if (!cancelled) setMeta(res.data); })
      .catch((e) => { if (!cancelled) setError(e.response?.data?.detail || "Failed to load filter options"); });
    return () => { cancelled = true; };
  }, [ledger]);

  const pickLedger = (k) => {
    if (k === ledger) return;
    setLedger(k);
    setMeta(null);
    setData({});
    setApplied({});
    setForm(EMPTY_FORM);
  };

  const centers = useMemo(() => {
    if (!meta) return [];
    if (!applied.governorate_id) return meta.centers;
    return meta.centers.filter((c) => String(c.governorate_id) === String(applied.governorate_id));
  }, [meta, applied.governorate_id]);

  const active = SECTIONS.find((s) => s.id === section);

  const load = useCallback(async () => {
    const keys = active.reports;
    setError("");
    setLoading((l) => ({ ...l, ...Object.fromEntries(keys.map((k) => [k, true])) }));
    await Promise.all(keys.map(async (key) => {
      try {
        const params = { ledger };
        Object.entries(applied).forEach(([k, v]) => { if (v) params[k] = v; });
        const res = await axios.get(`/api/v1/reports/${key}`, { headers: H(), params });
        setData((d) => ({ ...d, [key]: res.data }));
      } catch (e) {
        setError(e.response?.data?.detail || `Failed to load ${key}`);
      } finally {
        setLoading((l) => ({ ...l, [key]: false }));
      }
    }));
  }, [active, applied, ledger]);

  useEffect(() => { load(); }, [load]);

  const apply = () => setApplied({ ...form });
  const reset = () => {
    setForm(EMPTY_FORM);
    setApplied({});
  };

  const exportTable = async (key, fmt) => {
    try {
      const params = { fmt, ledger };
      Object.entries(applied).forEach(([k, v]) => { if (v) params[k] = v; });
      const res = await axios.get(`/api/v1/reports/${key}/export`, { headers: H(), params, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      // Ledger in the filename so a downloaded mudryia report can never be
      // mistaken for a company one.
      a.download = `report_${ledger}_${key}.${fmt}`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError("Export failed");
    }
  };

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v, ...(k === "governorate_id" ? { center_id: "" } : {}) }));

  const activeFiltersLabel = useMemo(() => {
    const parts = [];
    if (applied.date_from || applied.date_to) parts.push(`التاريخ: ${applied.date_from || "…"} ← ${applied.date_to || "…"}`);
    if (applied.governorate_id) parts.push("محافظة: " + (meta?.governorates.find((g) => String(g.id) === String(applied.governorate_id))?.name || ""));
    if (applied.request_status) parts.push("حالة: " + applied.request_status);
    if (applied.company) parts.push("شركة: " + applied.company);
    return parts.join("  •  ");
  }, [applied, meta]);

  return (
    <div className="flex flex-col h-full overflow-hidden bg-slate-50">
      {/* Header */}
      <div className="px-6 pt-6 pb-3 flex items-center justify-between print:hidden">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-slate-900 text-white flex items-center justify-center">
            <BarChart3 className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-800">التقارير</h1>
            <p className="text-sm text-gray-500">تقارير الطلبات والمستخدمين — إدارة</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="inline-flex items-center px-3 py-2 rounded-md text-xs font-semibold bg-white border border-gray-200 hover:bg-gray-50">
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> تحديث
          </button>
          <button onClick={() => window.print()} className="inline-flex items-center px-3 py-2 rounded-md text-xs font-semibold bg-slate-900 text-white hover:bg-slate-700">
            <Printer className="w-3.5 h-3.5 mr-1.5" /> طباعة / PDF
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="px-6 pb-3 print:hidden">
        <div className="bg-white border border-gray-200 rounded-lg p-3 mb-2 flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider text-gray-400">السجل</span>
          {[["company", "طلبات الشركة", Building2], ["mudryia", "طلبات المديرية", MapPinned]].map(([k, label, Icon]) => (
            <button key={k} onClick={() => pickLedger(k)}
              className={"px-3 py-1.5 rounded-md text-xs font-semibold inline-flex items-center gap-1.5 " +
                (ledger === k ? "bg-slate-900 text-white" : "bg-white text-slate-600 border border-gray-200 hover:bg-slate-50")}>
              <Icon className="w-3.5 h-3.5" /> {label}
            </button>
          ))}
          <span className="text-xs text-gray-400 mr-auto">
            {ledger === "mudryia" ? "طلبات المديرية — طبقة النقاط mudryia" : "طلبات الشركة — طبقات الأراضي والشغلات والنقاط"}
          </span>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3 flex flex-wrap gap-2 items-end">
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">من تاريخ</label>
            <input type="date" value={form.date_from} onChange={(e) => set("date_from", e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200" />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">إلى تاريخ</label>
            <input type="date" value={form.date_to} onChange={(e) => set("date_to", e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200" />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">المحافظة</label>
            <select value={form.governorate_id} onChange={(e) => set("governorate_id", e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200 max-w-[180px]">
              <option value="">الكل</option>
              {(meta?.governorates || []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">المركز</label>
            <select value={form.center_id} onChange={(e) => set("center_id", e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200 max-w-[180px]">
              <option value="">الكل</option>
              {centers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">الحالة</label>
            <select value={form.request_status} onChange={(e) => set("request_status", e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200 max-w-[160px]">
              <option value="">الكل</option>
              {(meta?.statuses || []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">حالة الرفع</label>
            <select value={form.survey_status} onChange={(e) => set("survey_status", e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200 max-w-[160px]">
              <option value="">الكل</option>
              {(meta?.survey_statuses || []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">الشركة</label>
            <select value={form.company} onChange={(e) => set("company", e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200 max-w-[140px]">
              <option value="">الكل</option>
              {(meta?.companies || []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">المساح</label>
            <select value={form.surveyor} onChange={(e) => set("surveyor", e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200 max-w-[140px]">
              <option value="">الكل</option>
              {(meta?.surveyors || []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">المكتب الفني</label>
            <select value={form.office} onChange={(e) => set("office", e.target.value)}
              className="px-2 py-1.5 text-sm rounded-md border border-gray-200 max-w-[140px]">
              <option value="">الكل</option>
              {(meta?.offices || []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <button onClick={apply} className="inline-flex items-center px-3 py-1.5 rounded-md text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700">
            تطبيق الفلاتر
          </button>
          <button onClick={reset} className="inline-flex items-center px-3 py-1.5 rounded-md text-xs font-semibold bg-gray-100 text-gray-700 hover:bg-gray-200">
            <RotateCcw className="w-3.5 h-3.5 mr-1.5" /> مسح
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="px-6 print:hidden">
        <div className="flex flex-wrap gap-1 border-b border-gray-200">
          {SECTIONS.map((s) => (
            <button key={s.id} onClick={() => setSection(s.id)}
              className={"px-3 py-2 text-sm font-semibold rounded-t-md transition-colors " +
                (section === s.id ? "bg-white border border-gray-200 border-b-white text-blue-700 -mb-px" : "text-gray-500 hover:text-slate-700")}>
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="px-6 pt-3 text-sm text-red-600 print:hidden">{error}</p>}

      {/* Content */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {/* Print header */}
        <div className="hidden print:block mb-4">
          <h1 className="text-xl font-bold">تقرير: {active.label}</h1>
          <p className="text-xs text-gray-500">{new Date().toLocaleString()} {activeFiltersLabel && " — " + activeFiltersLabel}</p>
        </div>

        {active.reports.map((key) => (
          <ReportTable
            key={key}
            reportKey={key}
            report={data[key]}
            busy={loading[key]}
            onExport={exportTable}
          />
        ))}
      </div>
    </div>
  );
}

function ReportTable({ reportKey, report, busy, onExport }) {
  if (busy && !report) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-10 flex items-center justify-center text-gray-400 text-sm mb-6">
        <Loader2 className="w-4 h-4 animate-spin mr-2" /> جارٍ التحميل…
      </div>
    );
  }
  if (!report) return null;

  const cols = [...report.columns, ...(report.extra_columns || [])];
  const rows = report.rows || [];
  const totals = report.totals || {};
  const firstKey = cols[0]?.key;
  const countKey = reportKey === "geometry_coverage" ? "with_geometry" : "total";
  const maxTotal = Math.max(1, ...rows.map((r) => Number(r[countKey]) || 0));

  return (
    <div className="bg-white border border-gray-200 rounded-lg mb-6 overflow-hidden">
      <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
        <h3 className="text-sm font-bold text-slate-700">{REPORT_TITLES[reportKey] || reportKey}
          <span className="ml-2 text-xs font-normal text-gray-400">({fmtNum(rows.length)} صف)</span>
        </h3>
        <div className="flex gap-1 print:hidden">
          <button onClick={() => onExport(reportKey, "csv")} title="CSV"
            className="inline-flex items-center px-2 py-1 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-700 hover:bg-emerald-100">
            <Download className="w-3 h-3 mr-1" /> CSV
          </button>
          <button onClick={() => onExport(reportKey, "xlsx")} title="Excel"
            className="inline-flex items-center px-2 py-1 rounded text-[11px] font-semibold bg-green-50 text-green-700 hover:bg-green-100">
            <Download className="w-3 h-3 mr-1" /> Excel
          </button>
        </div>
      </div>
      <div className="overflow-auto max-h-[calc(100vh-22rem)]">
        <table className="w-full text-sm border-collapse">
          <thead className="bg-slate-100 text-slate-500 text-xs uppercase tracking-wider sticky top-0">
            <tr>
              {cols.map((c) => (
                <th key={c.key} className={"px-3 py-2 font-semibold " + (c.type === "int" || c.type === "float" ? "text-right" : "text-left")}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-gray-50 hover:bg-blue-50/40">
                {cols.map((c, ci) => (
                  <td key={c.key} className={"px-3 py-1.5 " + (c.type === "int" || c.type === "float" ? "text-right tabular-nums " : "text-left ") +
                    (ci === 0 ? "text-slate-700 font-medium relative" : "text-slate-600")}>
                    {ci === 0 && (reportKey === "by_governorate" || reportKey === "by_center" || reportKey === "by_surveyor" || reportKey === "by_office" || reportKey === "by_company") && (
                      <span className="absolute left-0 top-0 h-full bg-blue-50 -z-0" style={{ width: `${(Number(r[countKey]) || 0) / maxTotal * 100}%` }} />
                    )}
                    <span className="relative z-10">
                      {c.key === "coverage_pct" ? fmtCell(r[c.key], "float") + "%" : fmtCell(r[c.key], c.type)}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={cols.length} className="px-3 py-8 text-center text-gray-400 text-sm">لا توجد بيانات مطابقة</td></tr>
            )}
          </tbody>
          {rows.length > 0 && Object.keys(totals).length > 0 && (
            <tfoot className="bg-slate-50 font-semibold text-slate-700 border-t-2 border-slate-200">
              <tr>
                {cols.map((c) => (
                  <td key={c.key} className={"px-3 py-2 " + (c.type === "int" || c.type === "float" ? "text-right tabular-nums" : "text-left")}>
                    {c.key === firstKey ? "الإجمالي" : (totals[c.key] !== undefined ? fmtCell(totals[c.key], c.type) : "")}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
