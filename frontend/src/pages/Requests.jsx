import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search, Save, History, Filter, ChevronDown, ChevronUp, MapPin, RotateCcw,
  Printer, BarChart3, X, Check, ArrowUp, ArrowDown, Bookmark, Trash2,
  Download, UserCheck, SlidersHorizontal, Map as MapIcon, Plus,
} from "lucide-react";
import axios from "axios";
import { ALL_COLS, DEFAULT_COLS } from "./requests/columns";

const FIELD_LABEL = "text-xs font-medium text-slate-600 mb-1 block";
const FIELD_INPUT = "w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-colors";
const FIELD_INPUT_SM = "w-full border border-slate-300 rounded-lg px-2 py-1 text-xs shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-colors";
const FIELD_LABEL_SM = "text-[11px] font-medium text-slate-600 mb-0.5 block";
const BASEMAP_WITH_GEOM = "✔ shapefile";
const BASEMAP_WITHOUT_GEOM = "Non_shapefile";

const FIELD_AR = {
  req_number: "رقم الطلب", applicant: "مقدم الطلب", phone: "الهاتف", address: "العنوان",
  area_value: "المساحة", governorate: "المحافظة", center: "المركز", village: "القرية",
  surveyor: "المساح", office: "المكتب الفني", request_status: "حالة الطلب",
  survey_status: "حالة المعاينة", reqra_number: "رقم التقنين", entry_date: "تاريخ الإدخال",
  survey_date: "تاريخ المعاينة", comment: "تعليق", assigned_to: "الإسناد",
};

function FormGroup({ title, children }) {
  return (
    <div className="border border-slate-200 rounded-xl p-4 space-y-3 bg-white shadow-sm">
      {title && <div className="text-xs font-semibold text-slate-700 uppercase tracking-wide mb-2">{title}</div>}
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function TextField({ label, value, onChange, type = "text", placeholder = "", disabled = false, err = "", small = false }) {
  return (
    <div>
      <label className={small ? FIELD_LABEL_SM : FIELD_LABEL}>{label}</label>
      <input type={type} value={value ?? ""} onChange={(e)=>onChange?.(e.target.value)} placeholder={placeholder} disabled={disabled} className={(small ? FIELD_INPUT_SM : FIELD_INPUT) + (disabled?" bg-slate-50":" bg-white") + (err?" border-red-400":"")} />
      {err && <p className="mt-1 text-[11px] text-red-600">{err}</p>}
    </div>
  );
}

function SelectField({ label, value, onChange, options = [], clearable = false, disabled = false, small = false, err = "" }) {
  return (
    <div>
      <label className={small ? FIELD_LABEL_SM : FIELD_LABEL}>{label}</label>
      <select value={value ?? ""} onChange={(e)=>onChange?.(e.target.value || null)} disabled={disabled} className={(small ? FIELD_INPUT_SM : FIELD_INPUT) + (disabled?" bg-slate-50":" bg-white")}>
        {clearable && <option value="">--</option>}
        {options.map((opt, i)=>{
          if (typeof opt === "object") return <option key={opt.value||i} value={opt.value}>{opt.label}</option>;
          return <option key={i} value={opt}>{opt}</option>;
        })}
      </select>
      {err && <p className="mt-1 text-[11px] text-red-600">{err}</p>}
    </div>
  );
}

function DropField({ label, value, onChange, options = [], clearable = false, disabled = false, multi = false }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef(null);
  const opts = (options || []).map((opt, i) => (typeof opt === "object"
    ? { value: String(opt.value ?? ""), label: opt.label ?? opt.value ?? "", key: "v" + String(opt.value ?? i) }
    : { value: String(opt), label: String(opt), key: i + ":" + String(opt) }));
  const labelOf = (v) => (opts.find((o) => o.value === String(v ?? "")) || {}).label || String(v ?? "");
  const selArr = multi ? (Array.isArray(value) ? value.map(String) : []) : [];
  const current = !multi ? opts.find((o) => o.value === String(value ?? "")) : null;
  const needle = q.trim().toLowerCase();
  const shown = needle ? opts.filter((o) => o.label.toLowerCase().includes(needle)) : opts;
  useEffect(() => {
    if (!open) return;
    setQ("");
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open ]);
  const toggle = (v) => {
    if (!multi) { onChange(v); setOpen(false); return; }
    onChange(selArr.includes(v) ? selArr.filter((x) => x !== v) : [...selArr, v]);
  };
  const btnText = !multi
    ? (current ? current.label : (clearable ? "--" : "اختر..."))
    : (selArr.length === 0 ? "--" : selArr.length === 1 ? labelOf(selArr[0]) : `${labelOf(selArr[0])} +${selArr.length - 1}`);
  return (
    <div>
      <label className={FIELD_LABEL_SM}>{label}{multi && selArr.length > 0 ? ` (${selArr.length})` : ""}</label>
      <div className="relative" ref={ref}>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
          className={(disabled ? "bg-slate-50 " : "bg-white ") + "w-full border border-slate-300 rounded-lg px-2 py-1 text-xs shadow-sm flex items-center justify-between gap-1 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-colors disabled:opacity-60"}
        >
          <span className={"truncate " + ((multi ? selArr.length : current) ? "text-slate-800" : "text-slate-400")}>
            {btnText}
          </span>
          <ChevronDown className={"w-3.5 h-3.5 text-slate-400 shrink-0 transition-transform " + (open ? "rotate-180" : "")} />
        </button>
        {open && !disabled && (
          <div className="absolute z-30 mt-1 w-full bg-white border border-slate-300 rounded-lg shadow-lg overflow-hidden">
            {opts.length > 10 && (
              <div className="p-1.5 border-b border-slate-100">
                <input
                  autoFocus
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="بحث..."
                  className="w-full px-2 py-1 text-xs border border-slate-200 rounded-md focus:outline-none focus:border-blue-400"
                />
              </div>
            )}
            <ul className="max-h-56 overflow-auto py-1">
              {clearable && (
                <li>
                  <button type="button" onClick={() => { onChange(multi ? [] : null); setOpen(false); }}
                    className="w-full text-right px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-100">
                    {multi ? "مسح الكل" : "--"}
                  </button>
                </li>
              )}
              {shown.map((o) => {
                const sel = multi ? selArr.includes(o.value) : !!(current && o.value === current.value);
                return (
                  <li key={o.key}>
                    <button type="button" onClick={() => toggle(o.value)}
                      className={"w-full text-right px-3 py-1.5 text-xs flex items-center justify-between gap-2 " + (sel ? "bg-blue-50 text-blue-800 font-semibold" : "text-slate-700 hover:bg-slate-100")}>
                      <span className="inline-flex items-center gap-2 truncate">
                        {multi && (
                          <span className={"w-3.5 h-3.5 rounded border flex items-center justify-center shrink-0 " + (sel ? "bg-blue-600 border-blue-600" : "border-slate-300 bg-white")}>
                            {sel && <Check className="w-2.5 h-2.5 text-white" />}
                          </span>
                        )}
                        <span className="truncate">{o.label}</span>
                      </span>
                      {!multi && sel && <Check className="w-3.5 h-3.5 shrink-0" />}
                    </button>
                  </li>
                );
              })}
              {!shown.length && (
                <li className="px-3 py-2 text-xs text-slate-400 text-center">لا نتائج</li>
              )}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function StaticField({ label, value, small = false }) {
  return (
    <div>
      <label className={small ? FIELD_LABEL_SM : FIELD_LABEL}>{label}</label>
      <div className="text-sm text-slate-700 py-1.5 px-3 bg-slate-50 rounded-lg border border-slate-200">{value ?? "—"}</div>
    </div>
  );
}

const api = axios;

function uniq(arr) { return Array.from(new Set((arr||[]).filter(x=>x!=null && x!==""))); }
function withCurrent(list, cur) { const s=new Set(list); if(cur!=null&&cur!=="") s.add(cur); return Array.from(s); }

function StatusBadge({ status }) {
  const st = (status || "").trim();
  const map = {
    "تم المعاينة": { cls: "bg-emerald-100 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
    "تمت المعاينة": { cls: "bg-emerald-100 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
    "تم المعاينه": { cls: "bg-emerald-100 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
    "تم الرفع وجاري المراجعة": { cls: "bg-blue-100 text-blue-700 border-blue-200", dot: "bg-blue-500" },
    "تم الرفع ع المنظومة": { cls: "bg-blue-100 text-blue-700 border-blue-200", dot: "bg-blue-500" },
    "لم يتم العمل عليه": { cls: "bg-slate-100 text-slate-700 border-slate-200", dot: "bg-slate-400" },
    "مقبول": { cls: "bg-emerald-100 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
    "مرفوض": { cls: "bg-red-100 text-red-700 border-red-200", dot: "bg-red-500" },
    "مرفوض مكتب فني": { cls: "bg-red-100 text-red-700 border-red-200", dot: "bg-red-500" },
    "لا يوجد": { cls: "bg-gray-100 text-gray-600 border-gray-200", dot: "bg-gray-400" },
    "جديد": { cls: "bg-slate-100 text-slate-700 border-slate-200", dot: "bg-slate-400" },
    "قيد الدراسة": { cls: "bg-amber-100 text-amber-700 border-amber-200", dot: "bg-amber-500" },
    "قيد المعاينة": { cls: "bg-amber-100 text-amber-700 border-amber-200", dot: "bg-amber-500" },
    "بالمراجعة الفنية": { cls: "bg-indigo-100 text-indigo-700 border-indigo-200", dot: "bg-indigo-500" },
    "تم الارسال": { cls: "bg-teal-100 text-teal-700 border-teal-200", dot: "bg-teal-500" },
    "جاري العمل عليه": { cls: "bg-amber-100 text-amber-700 border-amber-200", dot: "bg-amber-500" },
  };
  const cfg = map[st] || { cls: "bg-slate-100 text-slate-700 border-slate-200", dot: "bg-slate-400" };
  return (
    <span className={"inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold border " + cfg.cls}>
      <span className={"w-1.5 h-1.5 rounded-full " + cfg.dot}></span>
      {st || "غير محدد"}
    </span>
  );
}

const EMPTY_FILTERS = { q: "", status: [], survey_status: [], has_geometry: "", governorate: [], center: [], village: [], surveyor: [], office: [], unit_type: [], survey_comment: "", survey_comment_state: "", office_comment: "", office_comment_state: "", entry_from: "", entry_to: "", survey_from: "", survey_to: "", directorate_from: "", directorate_to: "", mine: false };
const MULTI_KEYS = ["status", "survey_status", "governorate", "center", "village", "surveyor", "office", "unit_type"];
const PARAM_OF = { status: "request_status", survey_status: "survey_status" };
// "(فارغ)" matches rows whose column is NULL / blank. The token travels to
// the backend inside the normal comma-separated list.
const EMPTY_VALUE = "__empty__";
const EMPTY_OPT = { value: EMPTY_VALUE, label: "(فارغ)" };
const withEmpty = (list) => [EMPTY_OPT, ...(list || [])];
// Staff dropdowns in the request form: the same "(فارغ)" option as the
// filters, so a request can explicitly carry no surveyor / no office.
const staffOptions = (list, cur) => [
  EMPTY_OPT,
  ...withCurrent(list, cur === EMPTY_VALUE ? "" : cur),
];

function readURLFilters() {
  const f = { ...EMPTY_FILTERS };
  try {
    const sp = new URLSearchParams(window.location.search);
    for (const k of Object.keys(f)) {
      if (k === "mine") { f.mine = sp.get("mine") === "1"; continue; }
      const v = sp.get(PARAM_OF[k] || k);
      if (v == null || v === "") continue;
      f[k] = MULTI_KEYS.includes(k) ? v.split(",").map((x) => x.trim()).filter(Boolean) : v;
    }
  } catch (e) {}
  return f;
}

export function RequestLedger({ base = "/api/v1/requests", title = "طلبات الشركات", mapLayer = "requests", emptyText = "لا توجد بيانات / جرب تعديل الفلاتر" }) {
  const navigate = useNavigate();
  const isMudryia = base.includes("mudryia");
  const [me, setMe] = useState(null);
  const canEdit = !!(me && (me.role === "admin" || me.role === "editor"));
  const canCreate = canEdit && !!(me && (me.permissions || []).includes(isMudryia ? "mudryia_requests" : "requests"));
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState(readURLFilters);
  const [dq, setDq] = useState(filters.q);
  const [page, setPage] = useState(() => { try { return Math.max(1, Number(new URLSearchParams(window.location.search).get("page")) || 1); } catch (e) { return 1; } });
  const [perPage, setPerPage] = useState(() => { try { const v = Number(new URLSearchParams(window.location.search).get("per_page")) || 50; return Math.min(500, Math.max(10, v)); } catch (e) { return 50; } });
  const [pages, setPages] = useState(1);
  const [dataTotal, setDataTotal] = useState(0);
  const [sort, setSort] = useState(() => {
    try {
      const sp = new URLSearchParams(window.location.search);
      return { key: sp.get("sort") || "id", dir: sp.get("dir") === "asc" ? "asc" : "desc" };
    } catch (e) { return { key: "id", dir: "desc" }; }
  });
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saveBusy, setSaveBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [note, setNote] = useState(null);
  const [formErrs, setFormErrs] = useState({});
  const [staff, setStaff] = useState({ staff: [], offices: [], rawStatuses: [], surveyStatuses: [], unitTypes: [] });
  const [centers, setCenters] = useState([]);
  const [governorates, setGovernorates] = useState([]);
  const [villages, setVillages] = useState([]);
  const [form, setForm] = useState({});
  const [formUnits, setFormUnits] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({});
  const [createErrs, setCreateErrs] = useState({});
  const [createErr, setCreateErr] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [stats, setStats] = useState(null);
  const [showStats, setShowStats] = useState(false);
  const [sel, setSel] = useState({});
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkSurveyor, setBulkSurveyor] = useState("");
  const [bulkOffice, setBulkOffice] = useState("");
  const [bulkTo, setBulkTo] = useState("");
  const [bulkOfficeComment, setBulkOfficeComment] = useState("");
  const [bulkClearOffice, setBulkClearOffice] = useState(false);
  const [bulkSurveyStatus, setBulkSurveyStatus] = useState("");
  const [bulkSurveyComment, setBulkSurveyComment] = useState("");
  const [bulkClearComment, setBulkClearComment] = useState(false);
  const [bulkAltDate, setBulkAltDate] = useState("");
  const [bulkClearAlt, setBulkClearAlt] = useState(false);
  const [bulkEntryDate, setBulkEntryDate] = useState("");
  const [bulkClearEntry, setBulkClearEntry] = useState(false);
  const bulkBaseRef = useRef(null);
  const [views, setViews] = useState({});
  const [viewName, setViewName] = useState("");
  const [cols, setCols] = useState(() => {
    try { const c = JSON.parse(localStorage.getItem("ledger_cols_" + base) || "null"); return Array.isArray(c) && c.length ? c : DEFAULT_COLS; } catch (e) { return DEFAULT_COLS; }
  });
  const [density, setDensity] = useState(() => { try { return localStorage.getItem("ledger_density_" + base) || "comfortable"; } catch (e) { return "comfortable"; } });
  const abortRef = useRef(null);
  const officeAutoRef = useRef(null);

  const setF = useCallback((k,v)=>{
    setForm(f=>({...f,[k]:v}));
    setFormErrs((e)=>{
      if(!e || !e[k]) return e;
      const n = {...e};
      delete n[k];
      return n;
    });
  },[]);

  // Debounce the free-text search so typing does not hammer the backend.
  useEffect(() => {
    const t = setTimeout(() => setDq(filters.q), 400);
    return () => clearTimeout(t);
  }, [filters.q]);

  // Keep the URL in sync so filtered views are shareable / survive refresh.
  useEffect(() => {
    try {
      const sp = new URLSearchParams();
      const F = { ...filters };
      if (F.q) sp.set("q", F.q);
      if (F.status.length) sp.set("request_status", F.status.join(","));
      if (F.survey_status.length) sp.set("survey_status", F.survey_status.join(","));
      if (F.has_geometry !== "") sp.set("has_geometry", F.has_geometry);
      for (const k of ["governorate","center","village","surveyor","office","unit_type"]) if (F[k].length) sp.set(k, F[k].join(","));
      if (F.survey_comment) sp.set("survey_comment", F.survey_comment);
      if (F.survey_comment_state) sp.set("survey_comment_state", F.survey_comment_state);
      if (F.office_comment) sp.set("office_comment", F.office_comment);
      if (F.office_comment_state) sp.set("office_comment_state", F.office_comment_state);
      for (const k of ["entry_from","entry_to","survey_from","survey_to","directorate_from","directorate_to"]) if (F[k]) sp.set(k, F[k]);
      if (F.mine) sp.set("mine", "1");
      if (page > 1) sp.set("page", String(page));
      if (perPage !== 50) sp.set("per_page", String(perPage));
      if (sort.key !== "id" || sort.dir !== "desc") { sp.set("sort", sort.key); sp.set("dir", sort.dir); }
      const qs = sp.toString();
      window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : ""));
    } catch (e) {}
  }, [filters, page, perPage, sort]);

  // Escape closes drawer / create modal.
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") { setOpen(null); setShowCreate(false); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  useEffect(() => {
    try { localStorage.setItem("ledger_cols_" + base, JSON.stringify(cols)); } catch (e) {}
  }, [cols, base]);
  useEffect(() => {
    try { localStorage.setItem("ledger_density_" + base, density); } catch (e) {}
  }, [density, base]);

  const surveyStatuses = uniq([...(staff.survStatuses || []), "تم المعاينة", "تم الرفع وجاري المراجعة", "لم يتم العمل عليه"]).sort((a, b) => a.localeCompare(b, "ar"));
  const requestStatuses = uniq([...(staff.reqStatuses || []), "مقبول", "مرفوض", "قيد الدراسة", "جديد", "لا يوجد"]).sort((a, b) => a.localeCompare(b, "ar"));
  const unitTypes = uniq(["مبني", "أرض"].concat(rows.map((r) => r.unit_type))).sort((a, b) => a.localeCompare(b, "ar"));
  const governorateNames = governorates.map((g) => g.name);
  const activeGov = governorates.find((g) => g.name === form.governorate);
  const centerOptions = centers.filter((c) => !activeGov || c.governorate_id === activeGov.id).map((c) => c.name);
  const activeCenter = centers.find((c) => c.name === form.center);
  const villageOptions = villages.filter((v) => !activeCenter || v.center_id === activeCenter.id).map((v) => v.name);
  const govNameById = (id) => (governorates.find((g) => g.id === id) || {}).name || "";
  const validCenterNames = (govs) => {
    const real = (govs || []).filter((n) => n !== EMPTY_VALUE);
    const list = real && real.length ? centers.filter((c) => real.includes(govNameById(c.governorate_id))) : centers;
    return uniq(list.map((c) => c.name).filter(Boolean));
  };
  const validVillageNames = (cens) => {
    const real = (cens || []).filter((n) => n !== EMPTY_VALUE);
    const ids = centers.filter((c) => real.includes(c.name)).map((c) => c.id);
    const list = real && real.length ? villages.filter((v) => ids.includes(v.center_id)) : villages;
    return uniq(list.map((v) => v.name).filter(Boolean));
  };
  const fCenterNames = validCenterNames(filters.governorate);
  const fVillageNames = validVillageNames(filters.center);
  const allSurveyorNames = uniq((staff.staff || []).filter(Boolean));
  const allOfficeNames = uniq((staff.offices || []).filter(Boolean));

  const selIds = useMemo(() => Object.keys(sel).filter((k) => sel[k]).map(Number), [sel]);
  useEffect(() => {
    const reset = () => {
      bulkBaseRef.current = null;
      setBulkSurveyor(""); setBulkOffice(""); setBulkTo("");
      setBulkSurveyStatus(""); setBulkSurveyComment(""); setBulkClearComment(false);
      setBulkOfficeComment(""); setBulkClearOffice(false);
      setBulkAltDate(""); setBulkClearAlt(false);
      setBulkEntryDate(""); setBulkClearEntry(false);
    };
    if (selIds.length !== 1) { reset(); return; }
    const row = rows.find((r) => r.id === selIds[0]);
    if (!row) { reset(); return; }
    const base = {
      surveyor: row.surveyor || "",
      office: row.office || "",
      request_status: row.request_status || "",
      office_comment: row.office_comment || "",
      survey_status: row.survey_status || "",
      survey_comment: row.survey_comment || "",
      entry_date: (row.entry_date || "").slice(0, 10),
      alt_survey_date: (row.alt_survey_date || "").slice(0, 10),
    };
    bulkBaseRef.current = base;
    setBulkSurveyor(base.surveyor); setBulkOffice(base.office); setBulkTo(base.request_status);
    setBulkSurveyStatus(base.survey_status); setBulkSurveyComment(base.survey_comment); setBulkClearComment(false);
    setBulkOfficeComment(base.office_comment); setBulkClearOffice(false);
    setBulkAltDate(base.alt_survey_date); setBulkClearAlt(false);
    setBulkEntryDate(base.entry_date); setBulkClearEntry(false);
  }, [selIds]);
  const visibleCols = useMemo(() => ALL_COLS.filter((c) => (c.always || cols.includes(c.key)) && (!c.mudryiaOnly || isMudryia)), [cols, isMudryia]);
  const cellPad = density === "compact" ? "px-3 py-1" : "px-4 py-2";

  const authH = () => ({ headers: { Authorization: "Bearer " + localStorage.getItem("token") } });

  const load = useCallback(async () => {
    if (abortRef.current) { try { abortRef.current.abort(); } catch (e) {} }
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", String(perPage));
      params.set("sort", sort.key);
      params.set("dir", sort.dir);
      if (dq) params.set("q", dq);
      if (filters.status.length) params.set("request_status", filters.status.join(","));
      if (filters.survey_status.length) params.set("survey_status", filters.survey_status.join(","));
      if (filters.has_geometry !== "") params.set("has_geometry", filters.has_geometry);
      if (filters.governorate.length) params.set("governorate", filters.governorate.join(","));
      if (filters.center.length) params.set("center", filters.center.join(","));
      if (filters.village.length) params.set("village", filters.village.join(","));
      if (filters.surveyor.length) params.set("surveyor", filters.surveyor.join(","));
      if (filters.office.length) params.set("office", filters.office.join(","));
      if (filters.unit_type.length) params.set("unit_type", filters.unit_type.join(","));
      if (filters.survey_comment) params.set("survey_comment", filters.survey_comment);
      if (filters.survey_comment_state) params.set("survey_comment_state", filters.survey_comment_state);
      if (filters.office_comment) params.set("office_comment", filters.office_comment);
      if (filters.office_comment_state) params.set("office_comment_state", filters.office_comment_state);
      if (filters.entry_from) params.set("entry_from", filters.entry_from);
      if (filters.entry_to) params.set("entry_to", filters.entry_to);
      if (filters.survey_from) params.set("survey_from", filters.survey_from);
      if (filters.survey_to) params.set("survey_to", filters.survey_to);
      if (filters.directorate_from) params.set("directorate_from", filters.directorate_from);
      if (filters.directorate_to) params.set("directorate_to", filters.directorate_to);
      if (filters.mine) params.set("assigned_to_me", "true");
      const r = await api.get(base + "?" + params.toString(), { ...authH(), signal: ctrl.signal });
      const data = r.data || r;
      setRows(data.items || data.rows || data.results || []);
      const pp = data.per_page || perPage;
      setPages(data.pages || Math.ceil((data.total||0)/pp) || 1);
      setDataTotal(data.total || data.count || 0);
    } catch (e) {
      if (e?.code === "ERR_CANCELED" || e?.name === "CanceledError") return;
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, [base, page, perPage, sort, dq, filters.status, filters.survey_status, filters.has_geometry, filters.governorate, filters.center, filters.village, filters.surveyor, filters.office, filters.unit_type, filters.survey_comment, filters.survey_comment_state, filters.office_comment, filters.office_comment_state, filters.entry_from, filters.entry_to, filters.survey_from, filters.survey_to, filters.mine]);

  useEffect(() => { load(); }, [load]);

  const loadStats = useCallback(async () => {
    try {
      const r = await api.get(base + "/stats", authH());
      setStats(r.data || r);
    } catch (e) { /* ignore */ }
  }, [base]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    api.get("/api/v1/auth/me", authH()).then((r) => setMe(r.data || r)).catch(() => {});
    loadStats();
  }, [base, loadStats]);

  const loadViews = useCallback(async () => {
    try {
      const r = await api.get("/api/v1/prefs", authH());
      const d = (r.data && r.data.data) || {};
      setViews(d.ledgerViews || {});
    } catch (e) { /* ignore */ }
  }, []);
  useEffect(() => { loadViews(); }, [loadViews]);

  useEffect(() => {
    const loadStaff = async () => {
      try {
        const token = localStorage.getItem("token");
        const h = { headers: { Authorization: "Bearer " + token } };
        const listOf = (d) => (Array.isArray(d?.data) ? d.data : Array.isArray(d) ? d : []);
        const [pSurveyor, pOffice, pUnits, pGovs, pCtrs, pVills, pReqSt, pSurvSt, pRawSt] = await Promise.all([
          api.get("/api/v1/lookups/values/surveyor", h).catch(() => ({ data: [] })),
          api.get("/api/v1/lookups/values/office", h).catch(() => ({ data: [] })),
          api.get("/api/v1/lookups/area_units", h),
          api.get("/api/v1/lookups/governorates", h),
          api.get("/api/v1/lookups/centers", h),
          api.get("/api/v1/lookups/villages", h),
          api.get("/api/v1/lookups/values/request_status", h).catch(() => ({ data: [] })),
          api.get("/api/v1/lookups/values/survey_status", h).catch(() => ({ data: [] })),
          api.get("/api/v1/lookups/values/raw_status", h).catch(() => ({ data: [] })),
        ]);
        const vnames = (d) => listOf(d).map((x) => (x && typeof x === "object" ? x.name : x)).filter(Boolean);
        setStaff({
          staff: vnames(pSurveyor),
          offices: vnames(pOffice),
          rawStatuses: vnames(pRawSt),
          reqStatuses: vnames(pReqSt),
          survStatuses: vnames(pSurvSt),
        });
        setFormUnits(listOf(pUnits));
        setGovernorates(listOf(pGovs));
        setCenters(listOf(pCtrs));
        setVillages(listOf(pVills));
      } catch (e) {
        // ignore
      }
    };
    loadStaff();
  }, [base, isMudryia]);

  // Auto-select the logged-in user as office when the field is empty and
  // their username/full name matches an office entry. Once per request;
  // never overwrites a stored value and stays editable afterwards.
  useEffect(() => {
    if (!detail || !me || !(staff.offices || []).length) return;
    if (officeAutoRef.current === detail.id) return;
    officeAutoRef.current = detail.id;
    const names = staff.offices.filter(Boolean);
    const uname = (me.username || "").trim();
    const fname = (me.full_name || "").trim();
    const match = names.find((n) => n === uname || n === fname);
    if (match) setForm((f) => (f.office ? f : { ...f, office: match }));
  }, [detail, me, staff.offices]);

  const openDetail = async (row) => {
    setOpen(row);
    setDetail(null);
    setDetailLoading(true);
    setFormErrs({});
    try {
      const d = await api.get(base + "/" + row.id, authH());
      const data = d.data || d;
      setDetail(data);
      setForm({ ...data });
    } finally {
      setDetailLoading(false);
    }
  };

  const validateForm = (f, requireNumber) => {
    const errs = {};
    // "(فارغ)" is an explicit "no value" for the staff fields, so it never
    // counts as a chosen surveyor.
    const surveyorName = (f.surveyor === EMPTY_VALUE ? "" : (f.surveyor || "")).toString().trim();
    if (requireNumber && !(f.req_number || "").toString().trim()) errs.req_number = "رقم الطلب مطلوب";
    const phone = (f.phone || "").toString().trim();
    if (phone && !/^[+\d][\d\s-]{5,}$/.test(phone)) errs.phone = "رقم هاتف غير صالح";
    if (f.area_value !== "" && f.area_value != null && !(Number(f.area_value) >= 0)) errs.area_value = "المساحة يجب أن تكون رقمًا موجبًا";
    if ((f.request_status || "") === "مقبول") {
      if (!["تم المعاينة", "تمت المعاينة", "تم المعاينه"].includes((f.survey_status || "").trim())) errs.survey_status = "يجب أن تكون تم المعاينة لقبول الطلب";
      if (!surveyorName) errs.surveyor = "يجب تحديد المساح لقبول الطلب";
      if (!(f.entry_date || "").toString().trim()) errs.entry_date = "تاريخ الإدخال فاضي — لا يمكن حفظ الطلب كـ«مقبول» قبل إدخاله";
    }
    if (f.geodesy_date && f.alt_survey_date && f.geodesy_date < f.alt_survey_date) errs.geodesy_date = "يجب أن يكون بعد تاريخ الرفع الميدانى";
    return errs;
  };

  const save = async () => {
    if (!detail) return;
    const errs = validateForm(form, false);
    setFormErrs(errs);
    if (Object.keys(errs).length) return;
    setSaveBusy(true);
    setNote(null);
    try {
      // "(فارغ)" is sent as an empty string, which is what clears the column
      // (and releases the assignee) on the server.
      const payload = { ...form };
      if (payload.surveyor === EMPTY_VALUE) payload.surveyor = "";
      if (payload.office === EMPTY_VALUE) payload.office = "";
      await api.patch(base + "/" + detail.id, payload, authH());
      setNote({ ok: "تم الحفظ بنجاح" });
      await openDetail(detail);
      await load();
      await loadStats();
    } catch (e) {
      setNote({ err: e?.response?.data?.detail || "فشل الحفظ" });
    } finally {
      setSaveBusy(false);
    }
  };

  const setC = (k, v) => setCreateForm((f) => ({ ...f, [k]: v }));

  const openCreate = () => {
    const names = uniq(staff.offices || []).filter(Boolean);
    const uname = (me?.username || "").trim();
    const fname = (me?.full_name || "").trim();
    const office = names.find((n) => n === uname || n === fname) || "";
    setCreateForm({
      req_number: "", reqra_number: "", applicant: "", phone: "", address: "",
      governorate: "", center: "", village: "",
      area_value: "", area_unit: "", unit_type: "",
      surveyor: "", office, survey_status: "", survey_date: "",
      request_status: "جديد", entry_date: "",
    });
    setCreateErrs({});
    setCreateErr("");
    setShowCreate(true);
  };

  const createRequest = async () => {
    if (createBusy) return;
    const errs = validateForm(createForm, true);
    setCreateErrs(errs);
    if (Object.keys(errs).length) return;
    setCreateBusy(true);
    setCreateErr("");
    try {
      const payload = {};
      Object.keys(createForm).forEach((k) => {
        let v = createForm[k];
        if (v === "" || v == null) return;
        if (v === EMPTY_VALUE) return; // "(فارغ)" = leave the field empty
        if (k === "req_number") v = v.toString().trim();
        if (k === "area_value") v = Number(v);
        payload[k] = v;
      });
      const r = await api.post(base, payload, authH());
      const created = r.data || r;
      setShowCreate(false);
      setNote({ ok: "تم إنشاء الطلب " + (created.req_number || "") });
      await load();
      await loadStats();
      if (created && created.id) openDetail(created);
    } catch (e) {
      setCreateErr(e?.response?.data?.detail || "فشل إنشاء الطلب");
    } finally {
      setCreateBusy(false);
    }
  };

  const buildFilterParams = (extra) => {
    const params = new URLSearchParams();
    if (filters.q) params.set("q", filters.q);
    if (filters.status.length) params.set("request_status", filters.status.join(","));
    if (filters.survey_status.length) params.set("survey_status", filters.survey_status.join(","));
    if (filters.has_geometry !== "") params.set("has_geometry", filters.has_geometry);
    if (filters.governorate.length) params.set("governorate", filters.governorate.join(","));
    if (filters.center.length) params.set("center", filters.center.join(","));
    if (filters.village.length) params.set("village", filters.village.join(","));
    if (filters.surveyor.length) params.set("surveyor", filters.surveyor.join(","));
    if (filters.office.length) params.set("office", filters.office.join(","));
    if (filters.unit_type.length) params.set("unit_type", filters.unit_type.join(","));
    if (filters.survey_comment) params.set("survey_comment", filters.survey_comment);
    if (filters.survey_comment_state) params.set("survey_comment_state", filters.survey_comment_state);
    if (filters.office_comment) params.set("office_comment", filters.office_comment);
    if (filters.office_comment_state) params.set("office_comment_state", filters.office_comment_state);
    if (filters.entry_from) params.set("entry_from", filters.entry_from);
    if (filters.entry_to) params.set("entry_to", filters.entry_to);
    if (filters.survey_from) params.set("survey_from", filters.survey_from);
    if (filters.survey_to) params.set("survey_to", filters.survey_to);
    if (filters.directorate_from) params.set("directorate_from", filters.directorate_from);
    if (filters.directorate_to) params.set("directorate_to", filters.directorate_to);
    if (filters.mine) params.set("assigned_to_me", "true");
    if (extra) for (const k of Object.keys(extra)) if (extra[k] != null && extra[k] !== "") params.set(k, extra[k]);
    return params;
  };

  // The ledger exports a styled .xlsx (coloured header, frozen and filterable
  // columns, real dates). `fmt=csv` is still available on the endpoint.
  const exportExcel = async (ids) => {
    if (exportBusy) return;
    setExportBusy(true);
    setNote(null);
    try {
      const params = ids ? new URLSearchParams({ ids: ids.join(",") }) : buildFilterParams();
      params.set("fmt", "xlsx");
      const r = await api.get(base + "/export?" + params.toString(), { ...authH(), responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      const now = new Date();
      const stamp = now.toISOString().slice(0, 10) + "_" + String(now.getHours()).padStart(2, "0") + String(now.getMinutes()).padStart(2, "0");
      a.download = (title.replace(/\s+/g, "_")) + "_" + stamp + (ids ? "_selected" : "") + ".xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setNote({ err: e?.response?.data?.detail || "فشل التصدير" });
    } finally {
      setExportBusy(false);
    }
  };

  const toggleSort = (sortKey) => {
    if (!sortKey) return;
    setSort((s) => (s.key === sortKey ? { key: sortKey, dir: s.dir === "asc" ? "desc" : "asc" } : { key: sortKey, dir: "asc" }));
    setPage(1);
  };

  const toggleCol = (key) => {
    setCols((c) => (c.includes(key) ? c.filter((k) => k !== key) : [...c, key]));
  };

  const applyView = (name) => {
    const v = views[name];
    if (!v) return;
    if (v.filters) setFilters({ ...EMPTY_FILTERS, ...v.filters });
    if (Array.isArray(v.cols) && v.cols.length) setCols(v.cols);
    if (v.perPage) setPerPage(v.perPage);
    if (v.density) setDensity(v.density);
    setPage(1);
  };

  const saveView = async () => {
    const name = (viewName || "").trim();
    if (!name) return;
    try {
      const cur = await api.get("/api/v1/prefs", authH());
      const data = (cur.data && cur.data.data) || {};
      const ledgerViews = { ...(data.ledgerViews || {}), [name]: { filters, cols, perPage, density } };
      await api.put("/api/v1/prefs", { data: { ...data, ledgerViews } }, authH());
      setViews(ledgerViews);
      setViewName("");
      setNote({ ok: "تم حفظ العرض" });
    } catch (e) {
      setNote({ err: "فشل حفظ العرض" });
    }
  };

  const deleteView = async (name) => {
    try {
      const cur = await api.get("/api/v1/prefs", authH());
      const data = (cur.data && cur.data.data) || {};
      const ledgerViews = { ...(data.ledgerViews || {}) };
      delete ledgerViews[name];
      await api.put("/api/v1/prefs", { data: { ...data, ledgerViews } }, authH());
      setViews(ledgerViews);
    } catch (e) { /* ignore */ }
  };

  const bulkFields = async () => {
    if (!selIds.length || bulkBusy) return;
    const payload = { ids: selIds };
    const clear = [];
    const baseRow = bulkBaseRef.current;
    const changed = (key, val) => (baseRow ? (val || "") !== (baseRow[key] || "") : !!val);
    if (bulkSurveyor && changed("surveyor", bulkSurveyor)) payload.surveyor = bulkSurveyor;
    if (bulkOffice && changed("office", bulkOffice)) payload.office = bulkOffice;
    if (bulkTo && changed("request_status", bulkTo)) payload.request_status = bulkTo;
    if (bulkSurveyStatus === "__clear__") clear.push("survey_status");
    else if (bulkSurveyStatus && changed("survey_status", bulkSurveyStatus)) payload.survey_status = bulkSurveyStatus;
    if (bulkClearComment) clear.push("survey_comment");
    else if (bulkSurveyComment.trim() && changed("survey_comment", bulkSurveyComment.trim())) payload.survey_comment = bulkSurveyComment.trim();
    if (bulkClearOffice) clear.push("office_comment");
    else if (bulkOfficeComment.trim() && changed("office_comment", bulkOfficeComment.trim())) payload.office_comment = bulkOfficeComment.trim();
    if (bulkClearAlt) clear.push("alt_survey_date");
    else if (bulkAltDate && changed("alt_survey_date", bulkAltDate)) payload.alt_survey_date = bulkAltDate;
    if (bulkClearEntry) clear.push("entry_date");
    else if (bulkEntryDate && changed("entry_date", bulkEntryDate)) payload.entry_date = bulkEntryDate;
    if (clear.length) payload.clear = clear;
    if (Object.keys(payload).length === 1) { setNote({ ok: "لا توجد تغييرات" }); return; }
    setBulkBusy(true);
    setNote(null);
    try {
      const r = await api.post(base + "/bulk-fields", payload, authH());
      setNote({ ok: r.data?.updated ? `تم تحديث ${r.data.updated} طلب` : "لا توجد تغييرات" });
      setSel({});
      setBulkSurveyor("");
      setBulkOffice("");
      setBulkTo("");
      setBulkSurveyStatus("");
      setBulkSurveyComment("");
      setBulkClearComment(false);
      setBulkOfficeComment("");
      setBulkClearOffice(false);
      setBulkAltDate("");
      setBulkClearAlt(false);
      setBulkEntryDate("");
      setBulkClearEntry(false);
      await load();
      await loadStats();
    } catch (e) {
      setNote({ err: e?.response?.data?.detail || "فشل تحديث الحقول" });
    } finally {
      setBulkBusy(false);
    }
  };

  const printReq = () => {
    if (!detail) return;
    const d = detail;
    const row = (k, v) => `<tr><td style="border:1px solid #999;padding:6px;background:#f3f4f6;font-weight:bold;width:35%">${k}</td><td style="border:1px solid #999;padding:6px">${v ?? "—"}</td></tr>`;
    const hist = (d.history || []).map((h) => `<li>${h.action} — ${h.username} — ${(h.created_at || "").replace("T", " ").slice(0, 19)}</li>`).join("");
    const html = `<html dir="rtl" lang="ar"><head><meta charset="utf-8"><title>${d.req_number || ""}</title></head><body style="font-family:Tahoma,Arial;padding:24px">`
      + `<h2>${title} — بطاقة طلب</h2>`
      + `<table style="border-collapse:collapse;width:100%;margin:12px 0">`
      + row("رقم الطلب", d.req_number) + row("مقدم الطلب", d.applicant) + row("الهاتف", d.phone)
      + row("العنوان", d.address) + row("المحافظة / المركز / القرية", [d.governorate, d.center, d.village].filter(Boolean).join(" / "))
      + row("المساحة", (d.area_value ?? "") + " " + (d.area_unit || "")) + row("المساح", d.surveyor)
      + row("المكتب الفني", d.office) + row("حالة الطلب", d.request_status) + row("حالة المعاينة", d.survey_status)
      + row("رقم التقنين", d.reqra_number) + row("تاريخ الإدخال", (d.entry_date || "").slice(0, 10))
      + row("تاريخ المعاينة", (d.survey_date || "").slice(0, 10))
      + `</table><h3>السجل (${(d.history || []).length})</h3><ul>${hist || "<li>لا يوجد سجل</li>"}</ul>`
      + `</body></html>`;
    const w = window.open("", "_blank", "width=800,height=900");
    if (!w) return;
    w.document.write(html);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 300);
  };

  const showOnMap = () => {
    const nums = rows.map((r) => r.req_number).filter(Boolean).slice(0, 200);
    if (!nums.length) return;
    navigate("/?reqs=" + encodeURIComponent(nums.join(",")) + "&ledger=" + (isMudryia ? "mudryia" : "company"));
  };

  const pageIds = rows.map((r) => r.id);
  const allPageSel = pageIds.length > 0 && pageIds.every((id) => sel[id]);
  const togglePage = () => {
    setSel((s) => {
      const n = { ...s };
      if (allPageSel) pageIds.forEach((id) => delete n[id]);
      else pageIds.forEach((id) => { n[id] = true; });
      return n;
    });
  };

  const renderCell = (r, key) => {
    switch (key) {
      case "req_number": return <span className="font-mono text-xs text-blue-700 whitespace-nowrap">{r.req_number}</span>;
      case "applicant": return <span className="text-slate-700 max-w-[220px] truncate block">{r.applicant || "—"}</span>;
      case "phone": return <span className="text-slate-600 whitespace-nowrap" dir="ltr">{r.phone || "—"}</span>;
      case "governorate": return <span className="text-slate-600">{r.governorate || "—"}</span>;
      case "center": return <span className="text-slate-600">{r.center || "—"}</span>;
      case "village": return <span className="text-slate-600">{r.village || "—"}</span>;
      case "area": return <span className="tabular-nums" dir="ltr">{r.area_value != null ? r.area_value : "—"} {r.area_unit || ""}</span>;
      case "unit_type": return <span className="text-slate-600">{r.unit_type || "—"}</span>;
      case "survey_comment": return <span title={r.survey_comment || ""} className="text-slate-600 max-w-[220px] truncate block">{r.survey_comment || "—"}</span>;
      case "office_comment": return <span title={r.office_comment || ""} className="text-slate-600 max-w-[220px] truncate block">{r.office_comment || "—"}</span>;
      case "surveyor": return <span className="text-slate-600">{r.surveyor || "—"}</span>;
      case "office": return <span className="text-slate-600">{r.office || "—"}</span>;
      case "survey_status": return <StatusBadge status={r.survey_status} />;
      case "request_status": return <StatusBadge status={r.request_status} />;
      case "reqra_number": return <span className="font-mono text-xs text-slate-600">{r.reqra_number || "—"}</span>;
      case "entry_date": return <span className="text-slate-600 whitespace-nowrap">{(r.entry_date || "").slice(0, 10) || "—"}</span>;
      case "directorate_date": return <span className="text-slate-600 whitespace-nowrap">{(r.directorate_date || "").slice(0, 10) || "—"}</span>;
      case "alt_survey_date": return <span className="text-slate-600 whitespace-nowrap">{(r.alt_survey_date || "").slice(0, 10) || "—"}</span>;
      case "company": return <span className="text-slate-600 max-w-[160px] truncate block">{r.company || "—"}</span>;
      case "geom": {
        const c = r.geometry_count ?? (r.has_geometry ? 1 : 0);
        return c > 0
          ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 text-emerald-700 border border-emerald-200">{c} معلم</span>
          : <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 text-slate-600 border border-slate-200">لا يوجد</span>;
      }
      case "actions": return (
        <button
          onClick={(e) => { e.stopPropagation(); navigate("/?req=" + encodeURIComponent(r.req_number) + (isMudryia ? "&layer=mudryia" : "")); }}
          title="عرض على الخريطة"
          className="p-1.5 rounded-lg text-slate-500 hover:bg-blue-50 hover:text-blue-700 transition-colors"
        >
          <MapPin className="w-4 h-4" />
        </button>
      );
      default: return null;
    }
  };

  const colSpan = visibleCols.length + 1;
  const cActiveGov = governorates.find((g) => g.name === createForm.governorate);
  const cCenterNames = uniq(centers.filter((c) => !cActiveGov || c.governorate_id === cActiveGov.id).map((c) => c.name));
  const cActiveCenter = centers.find((c) => c.name === createForm.center);
  const cVillageNames = uniq(villages.filter((v) => !cActiveCenter || v.center_id === cActiveCenter.id).map((v) => v.name));

  return (
    <div dir="rtl" className="h-[calc(100vh-4.5rem)] flex flex-col gap-4 p-4 bg-slate-50 overflow-hidden" style={{fontFamily:"IBM Plex Sans Arabic, Cairo, Tajawal, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif", fontSize:"14px"}}>
      <div className="flex-none flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-slate-800">{title}</h1>
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-200/70 text-slate-700 border border-slate-300">{dataTotal || rows.length}</span>
          {loading && <span className="text-xs text-blue-600 animate-pulse">جاري التحميل...</span>}
          {note && <span className={"text-xs font-medium " + (note.ok ? "text-emerald-600" : "text-red-600")}>{note.ok || note.err}</span>}
        </div>
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input value={filters.q} onChange={(e)=>{setFilters(f=>({...f,q:e.target.value})); setPage(1);}} placeholder="بحث: رقم الطلب، اسم، هاتف..." className="w-full pl-9 pr-8 py-1.5 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 shadow-sm" />
          {filters.q && (
            <button onClick={()=>{setFilters(f=>({...f,q:""})); setPage(1);}} title="مسح" className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {canCreate && (
            <button onClick={openCreate} title="إضافة طلب جديد" className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold bg-emerald-600 text-white border border-emerald-600 hover:bg-emerald-700 shadow-sm">
              <Plus className="w-4 h-4" /> طلب جديد
            </button>
          )}
          <button onClick={() => setShowStats((s) => !s)} title="إحصائيات" className={"inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium border shadow-sm " + (showStats ? "bg-blue-600 text-white border-blue-600" : "bg-white border-slate-200 hover:bg-slate-50")}>
            <BarChart3 className="w-4 h-4" /> إحصائيات
          </button>
          <button onClick={showOnMap} disabled={!rows.length} title="عرض نتائج الصفحة على الخريطة" className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-white border border-slate-200 hover:bg-slate-50 shadow-sm disabled:opacity-40">
            <MapIcon className="w-4 h-4" /> على الخريطة
          </button>
          <button onClick={() => exportExcel()} disabled={exportBusy} title="تصدير Excel منسّق" className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-100 text-slate-700 border border-slate-200 hover:bg-slate-200 shadow-sm disabled:opacity-50">
            <Download className="w-4 h-4" /> {exportBusy ? "جارٍ التصدير..." : "تصدير Excel"}
          </button>
          <button onClick={() => setShowFilters(s=>!s)} className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-white border border-slate-200 hover:bg-slate-50 shadow-sm">
            <Filter className="w-4 h-4" />
            فلترة
            {showFilters ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {showStats && stats && (
        <div className="flex-none bg-white rounded-xl shadow-sm border border-slate-200/70 p-4">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {[
              ["الإجمالي", stats.total],
              ["طلبات جديدة", stats.pending],
              ["قيد المعاينة", stats.in_survey],
              ["مقبول اليوم", stats.accepted_today],
              ["مرفوض اليوم", stats.rejected_today],
              ["أُدخل اليوم", stats.today_imported],
            ].map(([label, v]) => (
              <div key={label} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="text-[11px] text-slate-500">{label}</div>
                <div className="text-lg font-bold text-slate-800 tabular-nums">{Number(v || 0).toLocaleString("en-US")}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2 items-center">
            <span className="text-[11px] font-semibold text-slate-500">حسب الحالة:</span>
            {Object.entries(stats.by_status || {}).filter(([, n]) => n > 0).slice(0, 12).map(([s, n]) => (
              <button key={s} onClick={() => { setFilters((f) => ({ ...f, status: [s] })); setPage(1); setShowFilters(true); }} title="فلترة بهذه الحالة" className="inline-flex items-center gap-1.5 text-[11px] font-medium bg-slate-100 hover:bg-blue-50 border border-slate-200 rounded-full px-2 py-0.5">
                <StatusBadge status={s} /> <span className="tabular-nums text-slate-600">{Number(n).toLocaleString("en-US")}</span>
              </button>
            ))}
          </div>
          {!!(stats.by_center || []).length && (
            <div className="mt-2 flex flex-wrap gap-2 items-center">
              <span className="text-[11px] font-semibold text-slate-500">أعلى المراكز:</span>
              {(stats.by_center || []).slice(0, 8).map((c) => (
                <button key={c.name || "?"} onClick={() => { setFilters((f) => ({ ...f, center: c.name ? [c.name] : [] })); setPage(1); setShowFilters(true); }} title="فلترة بهذا المركز" className="text-[11px] font-medium bg-slate-100 hover:bg-blue-50 border border-slate-200 rounded-full px-2 py-0.5 text-slate-700">
                  {c.name || "—"} <span className="tabular-nums text-slate-500">({Number(c.count || 0).toLocaleString("en-US")})</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {selIds.length > 0 && (
        <div className="flex-none bg-blue-600 text-white rounded-xl shadow-sm px-4 py-2.5 flex items-center gap-3 flex-wrap">
          <span title="عدد الطلبات المحددة" className="w-6 h-6 rounded-full bg-red-600 text-white text-xs font-bold flex items-center justify-center shrink-0">{selIds.length}</span>
          {canEdit && (
            <>
              <div className="flex flex-col gap-1">
                <span className="text-[10px] font-semibold text-white/80 whitespace-nowrap">بيانات المعاينة</span>
                <div className="flex items-center gap-2 flex-wrap">
                  <select value={bulkSurveyor} onChange={(e) => setBulkSurveyor(e.target.value)} className="text-xs text-slate-800 rounded-lg px-2 py-1.5 bg-white min-w-[140px]">
                    <option value="">مساح...</option>
                    {withCurrent(allSurveyorNames, bulkSurveyor).map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                  <select value={bulkSurveyStatus} onChange={(e) => setBulkSurveyStatus(e.target.value)} title="حالة المعاينة" className="text-xs text-slate-800 rounded-lg px-2 py-1.5 bg-white min-w-[150px]">
                    <option value="">حالة المعاينة...</option>
                    <option value="__clear__">— مسح —</option>
                    {withCurrent(surveyStatuses, bulkSurveyStatus === "__clear__" ? "" : bulkSurveyStatus).map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <div className={"inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 " + (bulkClearComment ? "ring-2 ring-red-300" : "")}>
                    <input value={bulkSurveyComment} disabled={bulkClearComment} onChange={(e) => setBulkSurveyComment(e.target.value)} placeholder="تعليق المعاينة (المكتب الفني)" title="تعليق المعاينة (المكتب الفني)" className="text-xs text-slate-800 bg-transparent min-w-[190px] disabled:opacity-40" />
                    <button onClick={() => setBulkClearComment((v) => !v)} title={bulkClearComment ? "إلغاء المسح" : "مسح التعليق"} className={"p-0.5 rounded " + (bulkClearComment ? "text-red-600" : "text-slate-400 hover:text-red-600")}>
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className={"inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 " + (bulkClearAlt ? "ring-2 ring-red-300" : "")}>
                    <span className="text-[10px] text-slate-500 whitespace-nowrap">تاريخ الرفع الميدانى</span>
                    <input type="date" value={bulkAltDate} disabled={bulkClearAlt} onChange={(e) => setBulkAltDate(e.target.value)} className="text-xs text-slate-800 bg-transparent disabled:opacity-40" />
                    <button onClick={() => setBulkClearAlt((v) => !v)} title={bulkClearAlt ? "إلغاء المسح" : "مسح التاريخ"} className={"p-0.5 rounded " + (bulkClearAlt ? "text-red-600" : "text-slate-400 hover:text-red-600")}>
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
              <span className="self-stretch w-px bg-white/30" />
              <div className="flex flex-col gap-1">
                <span className="text-[10px] font-semibold text-white/80 whitespace-nowrap">بيانات المكتب الفنى</span>
                <div className="flex items-center gap-2 flex-wrap">
                  <select value={bulkOffice} onChange={(e) => setBulkOffice(e.target.value)} className="text-xs text-slate-800 rounded-lg px-2 py-1.5 bg-white min-w-[140px]">
                    <option value="">مكتب...</option>
                    {withCurrent(allOfficeNames, bulkOffice).map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                  <select value={bulkTo} onChange={(e) => setBulkTo(e.target.value)} className="text-xs text-slate-800 rounded-lg px-2 py-1.5 bg-white min-w-[140px]">
                    <option value="">حالة...</option>
                    {withCurrent(requestStatuses, bulkTo).map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <div className={"inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 " + (bulkClearOffice ? "ring-2 ring-red-300" : "")}>
                    <input value={bulkOfficeComment} disabled={bulkClearOffice} onChange={(e) => setBulkOfficeComment(e.target.value)} placeholder="تعليق المكتب الفني" title="تعليق المكتب الفني" className="text-xs text-slate-800 bg-transparent min-w-[170px] disabled:opacity-40" />
                    <button onClick={() => setBulkClearOffice((v) => !v)} title={bulkClearOffice ? "إلغاء المسح" : "مسح تعليق المكتب الفني"} className={"p-0.5 rounded " + (bulkClearOffice ? "text-red-600" : "text-slate-400 hover:text-red-600")}>
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className={"inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 " + (bulkClearEntry ? "ring-2 ring-red-300" : "")}>
                    <span className="text-[10px] text-slate-500 whitespace-nowrap">تاريخ الإدخال</span>
                    <input type="date" value={bulkEntryDate} disabled={bulkClearEntry} onChange={(e) => setBulkEntryDate(e.target.value)} className="text-xs text-slate-800 bg-transparent disabled:opacity-40" />
                    <button onClick={() => setBulkClearEntry((v) => !v)} title={bulkClearEntry ? "إلغاء المسح" : "مسح التاريخ"} className={"p-0.5 rounded " + (bulkClearEntry ? "text-red-600" : "text-slate-400 hover:text-red-600")}>
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
              <button onClick={bulkFields} disabled={bulkBusy || !(bulkSurveyor || bulkOffice || bulkTo || bulkSurveyStatus || bulkSurveyComment.trim() || bulkClearComment || bulkOfficeComment.trim() || bulkClearOffice || bulkAltDate || bulkClearAlt || bulkEntryDate || bulkClearEntry)} className="text-xs font-semibold bg-white text-blue-700 hover:bg-blue-50 rounded-lg px-3 py-1.5 disabled:opacity-40" title="يحدّث الحقول المدخلة فقط ويترك الباقي كما هو">تحديث الحقول</button>
            </>
          )}
          <button onClick={() => exportExcel(selIds)} disabled={exportBusy} className="text-xs font-semibold bg-white/20 hover:bg-white/30 rounded-lg px-3 py-1.5 disabled:opacity-40 inline-flex items-center gap-1">
            <Download className="w-3.5 h-3.5" /> تصدير المحدد
          </button>
          <button onClick={() => setSel({})} className="text-xs font-semibold bg-white/20 hover:bg-white/30 rounded-lg px-3 py-1.5">إلغاء التحديد</button>
        </div>
      )}

      {showFilters && (
        <div className="flex-none bg-white rounded-xl shadow-sm border border-slate-200/70 p-3">
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-2">
            <div className="flex items-end">
              <button onClick={() => { setFilters((f) => ({ ...f, mine: !f.mine })); setPage(1); }} className={"w-full justify-center inline-flex items-center gap-2 px-2 py-1 rounded-lg text-xs font-medium border shadow-sm " + (filters.mine ? "bg-blue-600 text-white border-blue-600" : "bg-white border-slate-200 hover:bg-slate-50")}>
                <UserCheck className="w-4 h-4" /> طلباتي
              </button>
            </div>
            <DropField multi label="حالة الطلب" value={filters.status} onChange={(v)=>{setFilters(f=>({...f,status:v||[]})); setPage(1);}} options={withEmpty(requestStatuses)} clearable />
            <DropField multi label="حالة المعاينة" value={filters.survey_status} onChange={(v)=>{setFilters(f=>({...f,survey_status:v||[]})); setPage(1);}} options={withEmpty(surveyStatuses)} clearable />
            <DropField label="وجود خريطة" value={filters.has_geometry} onChange={(v)=>{setFilters(f=>({...f,has_geometry:v||""})); setPage(1);}} options={[{value:"true",label:"يوجد"}, {value:"false",label:"لا يوجد"}]} clearable />
            <DropField multi label="المحافظة" value={filters.governorate} onChange={(v)=>{setFilters((f)=>{const govs=v||[];const vc=validCenterNames(govs);const nc=(f.center||[]).filter((n)=>vc.includes(n));const vv=validVillageNames(nc);return {...f,governorate:govs,center:nc,village:(f.village||[]).filter((n)=>vv.includes(n))};}); setPage(1);}} options={withEmpty(governorateNames)} clearable />
            <DropField multi label="المركز" value={filters.center} onChange={(v)=>{setFilters((f)=>{const nc=v||[];const vv=validVillageNames(nc);return {...f,center:nc,village:(f.village||[]).filter((n)=>vv.includes(n))};}); setPage(1);}} options={withEmpty(fCenterNames)} clearable />
            <DropField multi label="القرية" value={filters.village} onChange={(v)=>{setFilters(f=>({...f,village:v||[]})); setPage(1);}} options={withEmpty(fVillageNames)} clearable />
            <DropField multi label="المساح" value={filters.surveyor} onChange={(v)=>{setFilters(f=>({...f,surveyor:v||[]})); setPage(1);}} options={withEmpty(allSurveyorNames)} clearable />
            <DropField multi label="المكتب الفني" value={filters.office} onChange={(v)=>{setFilters(f=>({...f,office:v||[]})); setPage(1);}} options={withEmpty(allOfficeNames)} clearable />
            <DropField multi label="نوع الوحدة" value={filters.unit_type} onChange={(v)=>{setFilters(f=>({...f,unit_type:v||[]})); setPage(1);}} options={withEmpty(unitTypes)} clearable />
            <TextField small label="إدخال من" type="date" value={filters.entry_from} onChange={(v)=>{setFilters(f=>({...f,entry_from:v})); setPage(1);}} />
            <TextField small label="إدخال إلى" type="date" value={filters.entry_to} onChange={(v)=>{setFilters(f=>({...f,entry_to:v})); setPage(1);}} />
            <TextField small label="رفع ميدانى من" type="date" value={filters.survey_from} onChange={(v)=>{setFilters(f=>({...f,survey_from:v})); setPage(1);}} />
            <TextField small label="رفع ميدانى إلى" type="date" value={filters.survey_to} onChange={(v)=>{setFilters(f=>({...f,survey_to:v})); setPage(1);}} />
            {isMudryia && (
              <>
                <TextField small label="إرسال مديرية من" type="date" value={filters.directorate_from} onChange={(v)=>{setFilters(f=>({...f,directorate_from:v})); setPage(1);}} />
                <TextField small label="إرسال مديرية إلى" type="date" value={filters.directorate_to} onChange={(v)=>{setFilters(f=>({...f,directorate_to:v})); setPage(1);}} />
              </>
            )}
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100">
            <p className="text-[11px] font-semibold text-slate-500 mb-1.5">التعليقات</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <DropField label="تعليق المعاينة" value={filters.survey_comment_state} onChange={(v)=>{setFilters(f=>({...f,survey_comment_state:v||""})); setPage(1);}} options={[{value:"has",label:"يوجد تعليق"}, {value:"empty",label:"بدون تعليق"}]} clearable />
              <TextField small label="بحث في تعليق المعاينة" value={filters.survey_comment} onChange={(v)=>{setFilters(f=>({...f,survey_comment:v})); setPage(1);}} />
              <DropField label="تعليق المكتب الفني" value={filters.office_comment_state} onChange={(v)=>{setFilters(f=>({...f,office_comment_state:v||""})); setPage(1);}} options={[{value:"has",label:"يوجد تعليق"}, {value:"empty",label:"بدون تعليق"}]} clearable />
              <TextField small label="بحث في تعليق المكتب الفني" value={filters.office_comment} onChange={(v)=>{setFilters(f=>({...f,office_comment:v})); setPage(1);}} />
            </div>
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 flex items-start justify-between gap-2">
            <details className="flex-1 min-w-0">
            <summary className="text-xs font-semibold text-slate-500 hover:text-slate-700 cursor-pointer inline-flex items-center gap-1.5">
              <SlidersHorizontal className="w-3.5 h-3.5" /> الأعمدة والعروض المحفوظة
            </summary>
            <div className="mt-2 flex flex-wrap gap-2">
              {ALL_COLS.filter((c) => !c.always && (!c.mudryiaOnly || isMudryia)).map((c) => (
                <label key={c.key} className={"inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-2.5 py-1 border cursor-pointer " + (cols.includes(c.key) ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-slate-50 text-slate-500 border-slate-200")}>
                  <input type="checkbox" checked={cols.includes(c.key)} onChange={() => toggleCol(c.key)} className="accent-blue-600" />
                  {c.label}
                </label>
              ))}
              <button onClick={() => setDensity((d) => (d === "compact" ? "comfortable" : "compact"))} title="تبديل كثافة الصفوف" className="inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-2.5 py-1 border bg-slate-50 text-slate-500 border-slate-200">
                <SlidersHorizontal className="w-3.5 h-3.5" /> {density === "compact" ? "مريح" : "مضغوط"}
              </button>
            </div>
            <div className="mt-2 pt-2 border-t border-slate-100 flex items-center gap-2 flex-wrap">
              <select value="" onChange={(e) => { if (e.target.value) applyView(e.target.value); }} className="text-xs border border-slate-300 rounded-lg px-2 py-1 bg-white min-w-[140px]">
                <option value="">عرض محفوظ...</option>
                {Object.keys(views).map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <input value={viewName} onChange={(e) => setViewName(e.target.value)} placeholder="اسم العرض..." className="text-xs border border-slate-300 rounded-lg px-2 py-1 w-32" />
              <button onClick={saveView} disabled={!viewName.trim()} title="حفظ الفلاتر والأعمدة الحالية" className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-800 disabled:opacity-40">
                <Bookmark className="w-3.5 h-3.5" /> حفظ
              </button>
              {!!Object.keys(views).length && (
                <span className="inline-flex items-center gap-1">
                  {Object.keys(views).slice(0, 5).map((n) => (
                    <span key={n} className="inline-flex items-center gap-1 text-[11px] bg-slate-100 border border-slate-200 rounded-full px-2 py-0.5">
                      <button onClick={() => applyView(n)} className="text-slate-700 hover:text-blue-700">{n}</button>
                      <button onClick={() => deleteView(n)} title="حذف" className="text-slate-400 hover:text-red-600"><Trash2 className="w-3 h-3" /></button>
                    </span>
                  ))}
                </span>
              )}
            </div>
          </details>
          <button onClick={()=>{setFilters({...EMPTY_FILTERS}); setPage(1);}} className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 bg-white border border-slate-300 hover:bg-slate-50 shadow-sm">
            <RotateCcw className="w-3.5 h-3.5" /> إعادة تعيين
          </button>
          </div>
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-auto bg-white rounded-xl shadow-sm border border-slate-200/70">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs sticky top-0 z-10">
            <tr>
              <th className="px-3 py-2.5 border-b border-slate-200 w-8">
                <input type="checkbox" checked={allPageSel} onChange={togglePage} className="accent-blue-600" />
              </th>
              {visibleCols.map((c) => (
                <th key={c.key} onClick={() => toggleSort(c.sortKey)} title={c.sortKey ? "ترتيب" : ""} className={"px-4 py-2.5 font-semibold border-b border-slate-200 text-right " + (c.sortKey ? "cursor-pointer hover:text-blue-700 select-none" : "")}>
                  <span className="inline-flex items-center gap-1">
                    {c.label}
                    {c.sortKey && sort.key === c.sortKey && (
                      sort.dir === "asc" ? <ArrowUp className="w-3 h-3 text-blue-600" /> : <ArrowDown className="w-3 h-3 text-blue-600" />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} onClick={() => openDetail(r)} className={"border-b border-slate-100 hover:bg-blue-50/70 cursor-pointer transition-colors " + (open && open.id === r.id ? "bg-blue-50" : "") + (sel[r.id] ? " bg-blue-50/60" : "")}>
                <td className={cellPad} onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={!!sel[r.id]} onChange={() => setSel((s) => ({ ...s, [r.id]: !s[r.id] }))} className="accent-blue-600" />
                </td>
                {visibleCols.map((c) => (
                  <td key={c.key} className={cellPad + " text-slate-700" + (c.align === "right" ? " text-right" : "")}>{renderCell(r, c.key)}</td>
                ))}
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={colSpan} className="px-4 py-12 text-center text-slate-400 text-sm">{emptyText}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex-none flex items-center justify-between px-2">
        <div className="text-xs text-slate-500">
          عرض {dataTotal ? (page - 1) * perPage + 1 : 0}–{Math.min(page * perPage, dataTotal || 0)} من {dataTotal || 0}
        </div>
        <div className="flex items-center gap-2">
          <select value={perPage} onChange={(e)=>{setPerPage(Number(e.target.value)); setPage(1);}} className="px-2 py-1 text-xs border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500">
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
          </select>
          <button onClick={()=>setPage(Math.max(1, page-1))} disabled={page <= 1} className="px-3 py-1 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">السابق</button>
          <span className="text-xs text-slate-500">صفحة {page} من {Math.max(pages, 1)}</span>
          <button onClick={()=>setPage(Math.min(pages, page+1))} disabled={page >= pages} className="px-3 py-1 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">التالي</button>
        </div>
      </div>
      {open && (
        <div className="fixed inset-x-0 bottom-0 top-16 bg-black/50 z-40 flex items-start justify-end" onClick={() => setOpen(null)}>
          <div className="w-full max-w-xl h-full bg-slate-50 shadow-2xl overflow-auto rounded-l-2xl" dir="rtl" onClick={(e) => e.stopPropagation()}>
            <div className="p-5 space-y-4">
              <div className="flex items-center justify-between gap-2 flex-wrap sticky top-0 bg-slate-50 py-2 z-10 border-b border-slate-200">
                <h2 className="text-base font-semibold text-slate-800">تفاصيل الطلب {detail ? <span className="font-mono text-xs text-blue-700 font-normal">{detail.req_number}</span> : null}</h2>
                {detail && !detailLoading && (
                  <div className="flex items-center gap-1.5">
                    {(detail.geometry_count ?? (detail.has_geometry ? 1 : 0)) > 0 ? (
                      <span title="عدد المعالم الجغرافية" className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 text-emerald-700 border border-emerald-200">{detail.geometry_count ?? 1} معلم</span>
                    ) : (
                      <span title="عدد المعالم الجغرافية" className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 text-slate-600 border border-slate-200">بدون خريطة</span>
                    )}
                    <span title="الخريطة (Basemap)" className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-100 text-blue-700 border border-blue-200">{form.base_map || (detail.has_geometry ? BASEMAP_WITH_GEOM : BASEMAP_WITHOUT_GEOM)}</span>
                  </div>
                )}
                <div className="flex items-center gap-1">
                  <button onClick={() => setOpen(null)} className="p-1.5 rounded-lg hover:bg-slate-200 text-slate-600">✕</button>
                </div>
              </div>
              {detailLoading && <div className="text-sm text-slate-500">جاري التحميل...</div>}
              {detail && (
                <div className="space-y-4">
                  <FormGroup title="البيانات الأساسية">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <StaticField label="رقم الطلب" value={detail.req_number} />
                      <TextField label="رقم التقنين" value={form.reqra_number} onChange={(v)=>setF("reqra_number",v)} />
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <TextField label="اسم مقدم الطلب" value={form.applicant} onChange={(v)=>setF("applicant",v)} />
                      <TextField label="الهاتف" value={form.phone} onChange={(v)=>setF("phone",v)} err={formErrs.phone} />
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                      <SelectField label="المحافظة" value={form.governorate || ""} onChange={(v)=>{setF("governorate", v); setF("center", ""); setF("village", "");}} options={withCurrent(governorateNames, form.governorate)} clearable />
                      <SelectField label="المركز" value={form.center || ""} onChange={(v)=>{setF("center", v); setF("village", "");}} options={withCurrent(centerOptions, form.center)} clearable disabled={!form.governorate} />
                      <SelectField label="القرية" value={form.village || ""} onChange={(v)=>setF("village", v)} options={withCurrent(villageOptions, form.village)} clearable disabled={!form.center} />
                    </div>
                    <TextField label="العنوان" value={form.address} onChange={(v)=>setF("address",v)} />
                    <TextField label="العلامات المميزة" value={form.landmarks} onChange={(v)=>setF("landmarks",v)} />
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                      <TextField label="المساحة" type="number" value={form.area_value} onChange={(v)=>setF("area_value",v)} err={formErrs.area_value} />
                      <SelectField label="وحدة المساحة" value={(form.area_unit_id != null && Number(form.area_unit_id) !== 0) ? String(form.area_unit_id) : (form.area_unit || "")} onChange={(v)=>setF("area_unit_id", v ? Number(v) : null)} options={withCurrent(formUnits.map(u=>({value:String(u.id), label:u.name})), (form.area_unit||""))} clearable />
                      <SelectField label="نوع الوحدة" value={form.unit_type || ""} onChange={(v)=>setF("unit_type",v)} options={withCurrent(unitTypes, form.unit_type)} clearable />
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <TextField label="تاريخ التوزيع" type="date" value={form.distribution_date} onChange={(v)=>setF("distribution_date",v)} />
                      <TextField label="تاريخ المعاينة" type="date" value={form.survey_date} onChange={(v)=>setF("survey_date",v)} err={formErrs.survey_date} />
                      <TextField label="الفريق الميداني" value={form.field_team} onChange={(v)=>setF("field_team",v)} />
                      <TextField label="الشركة" value={form.company} onChange={(v)=>setF("company",v)} />
                    </div>
                  </FormGroup>
                  <FormGroup title="بيانات المعاينة">
                    <SelectField label="المساح" value={form.surveyor || ""} onChange={(v)=>setF("surveyor",v)} options={staffOptions(uniq(staff.staff), form.surveyor)} clearable err={formErrs.surveyor} />
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <SelectField label="حالة المعاينة" value={form.survey_status || ""} onChange={(v)=>setF("survey_status",v)} options={withCurrent(surveyStatuses, form.survey_status)} clearable err={formErrs.survey_status} />
                      <TextField label="تاريخ الرفع الميدانى" type="date" value={form.alt_survey_date} onChange={(v)=>setF("alt_survey_date",v)} />
                    </div>
                    <div>
                      <label className={FIELD_LABEL}>تعليق المعاينة (المكتب الفني)</label>
                      <textarea rows={2} value={form.survey_comment || ""} onChange={(e)=>setF("survey_comment",e.target.value)} className={FIELD_INPUT} />
                    </div>
                  </FormGroup>
                  <FormGroup title="بيانات المكتب الفني">
                    <SelectField label="المكتب الفني" value={form.office || ""} onChange={(v)=>setF("office",v)} options={staffOptions(uniq(staff.offices), form.office)} clearable err={formErrs.office} />
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <SelectField label="حالة ملفات Raw" value={form.raw_files} onChange={(v)=>setF("raw_files",v)} options={withCurrent(uniq(staff.rawStatuses), form.raw_files)} clearable />
                      <TextField label="تاريخ الإرسال الجيوديسي" type="date" value={form.geodesy_date} onChange={(v)=>setF("geodesy_date",v)} err={formErrs.geodesy_date} />
                      {isMudryia && (
                        <TextField label="تاريخ الإرسال للمديرية" type="date" value={form.directorate_date} onChange={(v)=>setF("directorate_date",v)} />
                      )}
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <SelectField label="حالة الطلب" value={form.request_status} onChange={(v)=>setF("request_status",v)} options={withCurrent(requestStatuses, form.request_status)} clearable />
                      <TextField label="تاريخ الإدخال" type="date" value={form.entry_date} onChange={(v)=>setF("entry_date",v)} err={formErrs.entry_date} />
                    </div>
                    <div>
                      <label className={FIELD_LABEL}>تعليق المكتب الفني</label>
                      <textarea rows={2} value={form.office_comment || ""} onChange={(e)=>setF("office_comment",e.target.value)} className={FIELD_INPUT} />
                    </div>
                    {detail.assigned_to && <StaticField label="مُسند إلى" value={detail.assigned_to} />}
                    {note && (
                      <p className={"mt-2 text-sm " + (note.ok ? "text-emerald-600" : "text-red-600")}>{note.ok || note.err}</p>
                    )}
                  </FormGroup>
                  <div className="border border-slate-200 rounded-xl p-4 bg-white shadow-sm">
                    <p className="text-xs font-semibold text-slate-700 uppercase tracking-wide mb-3 flex items-center gap-1.5">
                      <History className="w-4 h-4" /> السجل ({(detail.history || []).length})
                    </p>
                    <ul className="space-y-2">
                      {(detail.history || []).map((h, i) => (
                        <li key={i} className="text-xs text-slate-600 border-l-2 border-slate-200 pl-3 py-1">
                          <span className="font-medium">{h.action}</span>
                          <span className="text-slate-400"> by {h.username}</span>
                          {(h.old_values || h.new_values) && (
                            <div className="mt-1 space-y-0.5">
                              {Object.keys(h.new_values || h.old_values || {}).slice(0, 8).map((k) => (
                                <div key={k} className="text-[11px] text-slate-500">
                                  {FIELD_AR[k] || k}: <span className="line-through">{String((h.old_values || {})[k] ?? "—")}</span>
                                  {" ← "}<span className="font-medium text-slate-700">{String((h.new_values || {})[k] ?? "—")}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          <span className="block text-slate-400 mt-0.5">{h.created_at ? h.created_at.replace("T", " ").slice(0, 19) : ""}</span>
                        </li>
                      ))}
                      {!(detail.history || []).length && <li className="text-xs text-slate-400">لا يوجد سجل</li>}
                    </ul>
                  </div>
                  {canEdit && (
                    <div className="sticky bottom-0 bg-slate-50/95 backdrop-blur py-3 border-t border-slate-200">
                      <div className="flex items-center gap-2">
                      <button onClick={save} disabled={saveBusy} className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 shadow">
                        <Save className="w-4 h-4" /> {saveBusy ? "جارٍ الحفظ..." : "حفظ التعديلات"}
                      </button>
                      <button onClick={printReq} title="طباعة بطاقة الطلب" className="p-2.5 rounded-xl border border-slate-300 bg-white text-slate-600 hover:bg-slate-50 shadow shrink-0">
                        <Printer className="w-4 h-4" />
                      </button>
                      </div>
                      {note && (
                        <p className={"mt-2 text-sm text-center " + (note.ok ? "text-emerald-600" : "text-red-600")}>{note.ok || note.err}</p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setShowCreate(false)}>
          <div dir="rtl" className="w-full max-w-2xl max-h-[90vh] overflow-auto bg-slate-50 rounded-2xl shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 z-10 flex items-center justify-between gap-2 px-5 py-3 border-b border-slate-200 bg-slate-50">
              <h2 className="flex items-center gap-2 text-base font-semibold text-slate-800">
                <Plus className="w-4 h-4 text-emerald-600" /> طلب جديد
                <span className="text-xs font-normal text-slate-500">{title}</span>
              </h2>
              <button onClick={() => setShowCreate(false)} title="إغلاق" className="p-1.5 rounded-lg hover:bg-slate-200 text-slate-600"><X className="w-4 h-4" /></button>
            </div>
            <div className="p-5 space-y-4">
              {createErr && (
                <div className="text-sm font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{createErr}</div>
              )}
              <FormGroup title="البيانات الأساسية">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <TextField label="رقم الطلب *" value={createForm.req_number} onChange={(v)=>setC("req_number",v)} err={createErrs.req_number} placeholder="مثال: 1/2026" />
                  <TextField label="رقم التقنين" value={createForm.reqra_number} onChange={(v)=>setC("reqra_number",v)} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <TextField label="اسم مقدم الطلب" value={createForm.applicant} onChange={(v)=>setC("applicant",v)} />
                  <TextField label="الهاتف" value={createForm.phone} onChange={(v)=>setC("phone",v)} err={createErrs.phone} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  <SelectField label="المحافظة" value={createForm.governorate || ""} onChange={(v)=>setCreateForm(f=>({...f,governorate:v,center:null,village:null}))} options={withCurrent(governorateNames, createForm.governorate)} clearable />
                  <SelectField label="المركز" value={createForm.center || ""} onChange={(v)=>setCreateForm(f=>({...f,center:v,village:null}))} options={withCurrent(cCenterNames, createForm.center)} clearable disabled={!createForm.governorate} />
                  <SelectField label="القرية" value={createForm.village || ""} onChange={(v)=>setC("village",v)} options={withCurrent(cVillageNames, createForm.village)} clearable disabled={!createForm.center} />
                </div>
                <TextField label="العنوان" value={createForm.address} onChange={(v)=>setC("address",v)} />
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  <TextField label="المساحة" type="number" value={createForm.area_value} onChange={(v)=>setC("area_value",v)} err={createErrs.area_value} />
                  <SelectField label="وحدة المساحة" value={createForm.area_unit || ""} onChange={(v)=>setC("area_unit",v)} options={withCurrent(formUnits.map((u) => u.name), createForm.area_unit)} clearable />
                  <SelectField label="نوع الوحدة" value={createForm.unit_type || ""} onChange={(v)=>setC("unit_type",v)} options={withCurrent(unitTypes, createForm.unit_type)} clearable />
                </div>
              </FormGroup>
              <FormGroup title="بيانات المعاينة">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <SelectField label="المساح" value={createForm.surveyor || ""} onChange={(v)=>setC("surveyor",v)} options={staffOptions(allSurveyorNames, createForm.surveyor)} clearable err={createErrs.surveyor} />
                  <SelectField label="حالة المعاينة" value={createForm.survey_status || ""} onChange={(v)=>setC("survey_status",v)} options={withCurrent(surveyStatuses, createForm.survey_status)} clearable err={createErrs.survey_status} />
                  <TextField label="تاريخ المعاينة" type="date" value={createForm.survey_date || ""} onChange={(v)=>setC("survey_date",v)} />
                </div>
              </FormGroup>
              <FormGroup title="بيانات المكتب الفنى">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <SelectField label="المكتب الفني" value={createForm.office || ""} onChange={(v)=>setC("office",v)} options={staffOptions(allOfficeNames, createForm.office)} clearable err={createErrs.office} />
                  <SelectField label="حالة الطلب" value={createForm.request_status || ""} onChange={(v)=>setC("request_status",v)} options={withCurrent(requestStatuses, createForm.request_status)} clearable />
                  <TextField label="تاريخ الإدخال" type="date" value={createForm.entry_date} onChange={(v)=>setC("entry_date",v)} err={createErrs.entry_date} />
                </div>
              </FormGroup>
            </div>
            <div className="sticky bottom-0 flex items-center gap-2 border-t border-slate-200 bg-slate-50/95 backdrop-blur px-5 py-3">
              <button onClick={createRequest} disabled={createBusy} className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 shadow">
                <Plus className="w-4 h-4" /> {createBusy ? "جارٍ الإنشاء..." : "إنشاء الطلب"}
              </button>
              <button onClick={() => setShowCreate(false)} className="px-4 py-2.5 rounded-xl text-sm font-semibold border border-slate-300 bg-white text-slate-600 hover:bg-slate-50">إلغاء</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Requests() {
  return <RequestLedger base="/api/v1/requests" title="طلبات الشركات" mapLayer="requests" />;
}
