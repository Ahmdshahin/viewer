import { useState, useRef, useEffect } from "react";
import axios from "axios";
import { UploadCloud, FileUp, FileCheck2, FileDown, RefreshCcw, FileWarning, XCircle, MapPinned, Building2, AlertTriangle, Archive, PlusCircle } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

const fmt = (n, d = 0) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d }));
const headers = () => {
  const token = localStorage.getItem("token");
  return token ? { Authorization: "Bearer " + token } : {};
};

// The two request ledgers this page can fill. They are full mirrors of the same
// record shape, so both tabs work identically — only the API prefix and the
// page you land on afterwards differ.
const LEDGERS = {
  company: {
    base: "/api/v1/requests",
    label: "Company Requests",
    page: "/requests",
    Icon: Building2,
    hint: "intake sheet for the cadastral company ledger",
  },
  mudryia: {
    base: "/api/v1/mudryia-requests",
    label: "Mudryia Requests",
    page: "/mudryia-requests",
    Icon: MapPinned,
    hint: "intake sheet for the mudryia (طلبات المديرية) ledger",
  },
};

function Stat({ label, value, tone = "slate" }) {
  const tones = {
    slate: "border-slate-800",
    green: "border-green-600",
    amber: "border-amber-500",
    red: "border-red-600",
    blue: "border-blue-600",
  };
  return (
    <div className={"bg-white p-4 rounded shadow border-l-4 " + tones[tone]}>
      <p className="text-gray-500 text-xs uppercase tracking-wider">{label}</p>
      <p className="text-2xl font-bold mt-1 text-slate-800">{fmt(value)}</p>
    </div>
  );
}

function Chips({ title, items, empty }) {
  return (
    <div className="bg-white rounded shadow p-4">
      <p className="text-sm font-semibold text-slate-700 mb-2">{title}</p>
      {!items.length ? <p className="text-xs text-gray-400">{empty}</p> : (
        <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto">
          {items.map((it, i) => (
            <span key={i} className="text-[11px] font-mono bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded" title={it}>
              {String(it).slice(0, 38)}{String(it).length > 38 ? "…" : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ImportWorkbench() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [ledgerKey, setLedgerKey] = useState(
    () => (searchParams.get("ledger") === "mudryia" ? "mudryia" : "company")
  );
  const [allowed, setAllowed] = useState({ company: true, mudryia: true });
  const [tab, setTab] = useState("new");
  const [busy, setBusy] = useState(false);
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  // Legacy exports routinely carry columns the ledger has no field for; the
  // user opts in to ignoring those instead of having the import refused.
  const [force, setForce] = useState(false);
  const fileRef = useRef(null);
  const navigate = useNavigate();

  const ledger = LEDGERS[ledgerKey];
  const LedgerIcon = ledger.Icon;

  // Only offer a ledger the signed-in user may actually open.
  useEffect(() => {
    let cancelled = false;
    axios.get("/api/v1/auth/me", { headers: headers() })
      .then((res) => {
        if (cancelled) return;
        const perms = res.data.permissions || [];
        setAllowed({ company: perms.includes("requests"), mudryia: perms.includes("mudryia_requests") });
      })
      .catch(() => { /* keep both visible; the API will reject if not allowed */ });
    return () => { cancelled = true; };
  }, []);

  // If the chosen ledger is not permitted, fall back rather than 403 on upload.
  useEffect(() => {
    if (allowed[ledgerKey] === false) {
      setLedgerKey("company");
      setSearchParams({ ledger: "company" }, { replace: true });
    }
  }, [allowed, ledgerKey, setSearchParams]);

  const pickLedger = (k) => {
    setLedgerKey(k);
    setSearchParams({ ledger: k }, { replace: true });
    reset();
  };

  const reset = () => {
    setResult(null);
    setError("");
    setFileName("");
    setForce(false);
  };

  const onFile = (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) {
      setFileName(f.name);
      setError("");
      setResult(null);
    }
  };

  const upload = async () => {
    const f = fileRef.current && fileRef.current.files[0];
    if (!f) {
      setError("Choose a file first");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    const fd = new FormData();
    fd.append("file", f);
    const isIntake = tab === "new" || tab === "legacy";
    const url = isIntake
      ? `${ledger.base}/import${tab === "legacy" && force ? "?force=true" : ""}`
      : `${ledger.base}/import-result`;
    try {
      const res = await axios.post(url, fd, {
        headers: { ...headers(), "Content-Type": "multipart/form-data" },
        // A legacy export can hold tens of thousands of rows; the fill-in-place
        // pass runs one SAVEPOINT per row, so give it room.
        timeout: tab === "legacy" ? 1800000 : 120000,
      });
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || "Import failed");
    } finally {
      setBusy(false);
    }
  };

  // Pulls the blank .xlsx from the backend rather than generating it here, so the
  // headers are literally the ones the server's parser expects.
  const downloadTemplate = async () => {
    const url = tab === "new" ? `${ledger.base}/import-template` : `${ledger.base}/import-result-template`;
    try {
      const res = await axios.get(url, { headers: headers(), responseType: "blob", timeout: 60000 });
      const name =
        (res.headers["content-disposition"] || "").match(/filename="?([^"]+)"?/)?.[1] ||
        (tab === "new" ? `${ledgerKey}_requests_template.xlsx` : `${ledgerKey}_results_template.xlsx`);
      const href = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = href;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
    } catch {
      setError("Could not download the template");
    }
  };

  const r = result;
  const isIntake = tab === "new" || tab === "legacy";

  return (
    <div className="p-8 overflow-y-auto h-full">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Data Import</h1>
          <p className="text-sm text-gray-500 mt-1">Upload the daily intake sheet, the acceptance/rejection results, or a legacy system export</p>
        </div>
        <button
          onClick={() => navigate(ledger.page)}
          className="inline-flex items-center px-3 py-2 rounded-md text-xs font-semibold bg-slate-900 text-white hover:bg-slate-700"
        >
          <LedgerIcon className="w-3.5 h-3.5 mr-1.5" /> {ledger.label}
        </button>
      </div>

      {/* Target ledger */}
      <div className="mb-5">
        <p className="text-[11px] uppercase tracking-wider text-gray-400 mb-2">Import into</p>
        <div className="flex gap-2 flex-wrap">
          {Object.entries(LEDGERS).map(([k, L]) => {
            const on = k === ledgerKey;
            const Icon = L.Icon;
            const disabled = allowed[k] === false;
            return (
              <button
                key={k}
                onClick={() => pickLedger(k)}
                disabled={disabled}
                title={disabled ? `You do not have the ${k === "mudryia" ? "Mudryia Requests" : "Requests"} permission` : L.hint}
                className={"px-4 py-2 rounded-md text-sm font-semibold flex items-center gap-2 " +
                  (on ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100") +
                  (disabled ? " opacity-40 cursor-not-allowed" : "")}
              >
                <Icon className="w-4 h-4" /> {L.label}
              </button>
            );
          })}
        </div>
        <p className="text-xs text-gray-400 mt-2">
          Rows are matched by <span className="font-mono">Req_Number</span> against the <span className="font-semibold">{ledger.label}</span> ledger.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => { setTab("new"); reset(); }}
          className={"px-4 py-2 rounded-md text-sm font-semibold flex items-center gap-2 " +
            (tab === "new" ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100")}
        >
          <FileUp className="w-4 h-4" /> New requests
        </button>
        <button
          onClick={() => { setTab("result"); reset(); }}
          className={"px-4 py-2 rounded-md text-sm font-semibold flex items-center gap-2 " +
            (tab === "result" ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100")}
        >
          <FileCheck2 className="w-4 h-4" /> Acceptance / rejection results
        </button>
        <button
          onClick={() => { setTab("legacy"); reset(); }}
          className={"px-4 py-2 rounded-md text-sm font-semibold flex items-center gap-2 " +
            (tab === "legacy" ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100")}
        >
          <Archive className="w-4 h-4" /> Legacy data
        </button>
      </div>

      {/* Upload card */}
      <div className="bg-white rounded shadow p-6 mb-6">
        {tab === "new" ? (
          <p className="text-sm text-gray-600 mb-1">
            <span className="font-semibold">New intake sheet</span> — rows are matched by <span className="font-mono">Req_Number</span> (رقم الطلب).
            Existing numbers are not overwritten: the import only fills the fields they are still missing.
          </p>
        ) : tab === "legacy" ? (
          <p className="text-sm text-gray-600 mb-1">
            <span className="font-semibold">Legacy export</span> — any old system dump (CSV/XLSX with its original headers, e.g. 8888.csv or docs/1.csv).
            Headers are matched tolerantly — Arabic spelling variants, extra columns and known aliases all resolve to the right field —
            and rows matched by <span className="font-mono">رقم الطلب</span> <span className="font-semibold">fill in</span> the fields their
            stored record is missing. Existing values are never changed, and nothing is deleted.
          </p>
        ) : (
          <p className="text-sm text-gray-600 mb-1">
            <span className="font-semibold">Results from the external system</span> — each row updates the matching request to <span className="font-semibold">مقبول</span> or <span className="font-semibold">مرفوض</span>. A notification is sent to all active users.
          </p>
        )}
        <p className="text-xs text-gray-400 mb-4">Accepted formats: .csv, .xlsx, .xlsm</p>

        {tab === "legacy" && (
          <label className="flex items-start gap-2 mb-4 text-xs text-gray-600 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span>
              Continue even if the sheet is <span className="font-semibold">missing required columns</span> (force).
              Unrecognised columns are always listed in the report below so you can see exactly what was left out.
            </span>
          </label>
        )}

        <div className="flex items-center gap-3 flex-wrap">
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm" onChange={onFile}
            className="text-sm text-gray-600 file:mr-3 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200" />
          <button
            onClick={upload}
            disabled={busy}
            className="inline-flex items-center px-4 py-2 rounded-md text-sm font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <UploadCloud className={"w-4 h-4 mr-1.5 " + (busy ? "animate-bounce" : "")} />
            {busy ? (tab === "legacy" ? "Importing legacy data…" : "Uploading…") : "Upload & import"}
          </button>
          {tab !== "legacy" && (
            <button
              onClick={downloadTemplate}
              className="inline-flex items-center px-4 py-2 rounded-md text-sm font-semibold bg-white text-slate-700 border border-slate-300 hover:bg-slate-100"
            >
              <FileDown className="w-4 h-4 mr-1.5" /> Download blank template
            </button>
          )}
        </div>

        {fileName && !error && <p className="text-xs text-gray-400 mt-2">Selected: {fileName}</p>}
        {error && (
          <p className="mt-3 text-sm text-red-600 flex items-center gap-1.5">
            <XCircle className="w-4 h-4" /> {error}
          </p>
        )}
      </div>

      {/* Results */}
      {r && (
        <div className="space-y-4">
          {(r.unmapped_columns && r.unmapped_columns.length > 0) && (
            <div className="bg-white rounded shadow p-4 border-l-4 border-amber-500">
              <p className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-amber-500" />
                {r.unmapped_columns.length} column(s) in your sheet were not recognised and were ignored
              </p>
              <div className="flex flex-wrap gap-1.5">
                {r.unmapped_columns.map((c) => (
                  <span key={c} className="text-[11px] font-mono bg-amber-50 text-amber-800 border border-amber-200 px-1.5 py-0.5 rounded">
                    {c}
                  </span>
                ))}
              </div>
              <p className="text-xs text-gray-400 mt-2">
                If any of these should have been imported, the header text needs to match the expected name.
              </p>
            </div>
          )}
          {(r.missing_fields && r.missing_fields.length > 0) && (
            <div className="bg-white rounded shadow p-4 border-l-4 border-red-500">
              <p className="text-sm font-semibold text-slate-700 mb-1 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-red-500" />
                Your sheet supplied no value for {r.missing_fields.length} required field(s)
              </p>
              <p className="text-xs text-gray-500">
                {r.missing_fields.join(" · ")}
              </p>
              <p className="text-xs text-gray-400 mt-2">
                Every row in that sheet will be stored without these, which is usually a
                sign the column headers did not match. Download the blank template to see
                the expected names.
              </p>
            </div>
          )}
          {isIntake ? (
            <>
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                <Stat label="Added" value={r.added} tone="green" />
                <Stat label="Updated (filled)" value={r.updated ?? "—"} tone="blue" />
                <Stat label="Duplicated (skipped)" value={r.duplicated} tone="amber" />
                <Stat label="Errors" value={r.errors} tone="red" />
                <Stat label="Uploaded by" value={1} tone="blue" />
              </div>
              {typeof r.rows_with_number === "number" && (
                <p className="text-xs text-gray-500">
                  Sheet read: {fmt(r.rows_with_number)} row(s) with a request number ·
                  {" "}{fmt(r.avg_fields_per_row, 1)} mapped field(s) per row on average ·
                  {" "}{fmt(r.skipped_no_number)} reference row(s) without a number skipped
                </p>
              )}
              {r.created_lookups && Object.values(r.created_lookups).flat().length > 0 && (
                <div className="bg-white rounded shadow p-4 border-l-4 border-emerald-500">
                  <p className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-1.5">
                    <PlusCircle className="w-4 h-4 text-emerald-500" />
                    {Object.values(r.created_lookups).flat().length} new lookup value(s) were
                    added to the shared tables
                  </p>
                  {["governorates", "centers", "villages"].map((kind) =>
                    (r.created_lookups[kind] || []).length > 0 ? (
                      <div key={kind} className="mb-1.5 last:mb-0">
                        <p className="text-xs text-gray-500 mb-1">{kind}:</p>
                        <div className="flex flex-wrap gap-1.5">
                          {r.created_lookups[kind].map((n) => (
                            <span
                              key={n}
                              className="text-[11px] bg-emerald-50 text-emerald-800 border border-emerald-200 px-1.5 py-0.5 rounded"
                            >
                              {n}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null
                  )}
                </div>
              )}
              {(r.updated_numbers && r.updated_numbers.length > 0) && (
                <Chips title="Updated request numbers" items={r.updated_numbers} empty="" />
              )}
              {(r.added_numbers && r.added_numbers.length > 0) && (
                <Chips title="Added request numbers" items={r.added_numbers} empty="" />
              )}
              {(r.duplicates && r.duplicates.length > 0) && (
                <Chips title="Already existing (skipped)" items={r.duplicates} empty="" />
              )}
              {(r.error_details && r.error_details.length > 0) && (
                <div className="bg-white rounded shadow p-4">
                  <p className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-1.5">
                    <FileWarning className="w-4 h-4 text-amber-500" /> Row errors
                  </p>
                  <ul className="text-xs text-gray-600 space-y-1 max-h-40 overflow-y-auto">
                    {r.error_details.map((e, i) => (
                      <li key={i} className="font-mono">{e.req_number || ""} — {e.reason}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <Stat label="Accepted" value={r.accepted} tone="green" />
                <Stat label="Rejected" value={r.rejected} tone="red" />
                <Stat label="Updated" value={r.updated} tone="blue" />
                <Stat label="Not found" value={r.not_found} tone="amber" />
              </div>
              {(r.updated_numbers && r.updated_numbers.length > 0) && (
                <Chips title="Updated request numbers" items={r.updated_numbers} empty="" />
              )}
              {(r.not_found_numbers && r.not_found_numbers.length > 0) && (
                <Chips title="Numbers not in the ledger (skipped)" items={r.not_found_numbers} empty="" />
              )}
            </>
          )}
        </div>
      )}

      {!r && !busy && (
        <div className="bg-white rounded shadow p-8 text-center text-gray-400">
          <RefreshCcw className="w-8 h-8 mx-auto mb-2 opacity-40" />
          <p className="text-sm">Pick a file and press upload to see the import summary here</p>
        </div>
      )}
    </div>
  );
}