import axios from "axios";

export const ALLOWED = new Set([".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".shp.xml", ".csv", ".xlsx", ".xls", ".json", ".geojson"]);
export const ONE_GIB = 1024 * 1024 * 1024;
export const QUOTA = 5 * ONE_GIB;

export const authH = () => ({ Authorization: "Bearer " + localStorage.getItem("token") });

export const fmtBytes = (n) => {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(v >= 100 || i === 0 ? 0 : 1) + " " + u[i];
};

// Strip the picked root folder: webkitRelativePath "Batch/req1/a.shp"
// must land as "req1/a.shp" so each request folder stays top-level.
export const serverRel = (f) => {
  const w = f.webkitRelativePath || f.name || "";
  const parts = w.split("/").filter(Boolean);
  if (parts.length > 1) {
    const rel = parts.slice(1).join("/");
    if (rel) return rel;
  }
  return f.name || "file";
};

// Client-side pre-check: broken shapefile sets block, dubious ones warn.
export function analyzePicked(files) {
  const errors = [];
  const warnings = [];
  let total = 0;
  const sets = new Map();
  for (const f of files) {
    total += f.size || 0;
    const rel = serverRel(f);
    const name = rel.split("/").pop();
    const lower = name.toLowerCase();
    if (lower.endsWith(".zip")) {
      errors.push(`"${name}" is a zip — extract it on your PC first.`);
      continue;
    }
    let ext = "";
    const dot = name.lastIndexOf(".");
    if (lower.endsWith(".shp.xml")) ext = ".shp.xml";
    else if (dot >= 0) ext = name.slice(dot).toLowerCase();
    if (!ALLOWED.has(ext)) {
      errors.push(`"${name}" has unsupported type (${ext || "no extension"}).`);
      continue;
    }
    const base = (lower.endsWith(".shp.xml") ? name.slice(0, -8) : dot >= 0 ? name.slice(0, dot) : name).toLowerCase();
    const dir = rel.split("/").slice(0, -1).join("/");
    const key = dir + "\n" + base;
    if (!sets.has(key)) sets.set(key, new Set());
    sets.get(key).add(ext);
    if ((f.size || 0) > ONE_GIB) errors.push(`"${name}" exceeds the 1 GiB per-file limit.`);
  }
  if (total > QUOTA) errors.push("Selection exceeds the 5 GiB session quota — split it into smaller batches.");
  let shpCount = 0;
  for (const [key, exts] of sets) {
    if (!exts.has(".shp")) continue;
    shpCount++;
    const base = key.split("\n")[1];
    const missing = [".shx", ".dbf"].filter((e) => !exts.has(e));
    if (missing.length) errors.push(`"${base}" is missing ${missing.join(" + ")} — a shapefile needs .shp + .shx + .dbf.`);
    else if (!exts.has(".prj")) warnings.push(`"${base}" has no .prj — the coordinate system may be guessed.`);
  }
  return { errors, warnings, total, shpCount, count: files.length };
}

export async function initStaging() {
  const r = await axios.post("/api/v1/staging/init", {}, { headers: authH() });
  return r.data;
}

export async function uploadOne(sessionId, file, rel, onProgress) {
  const fd = new FormData();
  fd.append("session_id", sessionId);
  fd.append("relative_path", rel);
  fd.append("file", file);
  await axios.post("/api/v1/staging/upload", fd, {
    headers: { ...authH(), "Content-Type": "multipart/form-data" },
    onUploadProgress: onProgress,
  });
}

export async function deleteStaging(sessionId) {
  if (!sessionId) return;
  try {
    await axios.delete("/api/v1/staging/session", { params: { session_id: sessionId }, headers: authH() });
  } catch (e) { /* ignore */ }
}
