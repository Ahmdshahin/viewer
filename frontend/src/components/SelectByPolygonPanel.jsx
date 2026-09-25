import React, { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import {
  X, Loader2, Check, Undo2, MousePointer2, ZoomIn, FolderOutput,
  AlertTriangle, CheckCircle2, RefreshCw, Layers
} from "lucide-react";

const authHeaders = () => ({ Authorization: "Bearer " + localStorage.getItem("token") });
const pointKey = (p) => p && p[0].toFixed(6) + "," + p[1].toFixed(6);

/*
 * Helpers: distance, self-intersection, and a small auto-repair step.
 * Vertices are [lng, lat] pairs. Rings are open (the closing vertex is
 * implied and added by the backend intersect call).
 */

const distMeters = (a, b) => {
  if (!a || !b) return NaN;
  const R = 6371008.8;
  const dLat = (b[1] - a[1]) * Math.PI / 180;
  const dLng = (b[0] - a[0]) * Math.PI / 180;
  const s = Math.sin(dLat / 2) ** 2 +
    Math.cos(a[1] * Math.PI / 180) * Math.cos(b[1] * Math.PI / 180) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
};

const orient = (o, a, b) => {
  const v = (b[0] - a[0]) * (o[1] - a[1]) - (b[1] - a[1]) * (o[0] - a[0]);
  return v > 0 ? 1 : v < 0 ? -1 : 0;
};

const onSeg = (p, a, b) => orient(p, a, b) === 0 &&
  Math.min(a[0], b[0]) <= p[0] && p[0] <= Math.max(a[0], b[0]) &&
  Math.min(a[1], b[1]) <= p[1] && p[1] <= Math.max(a[1], b[1]);

const segsIntersect = (p1, p2, p3, p4) => {
  const d1 = orient(p3, p4, p1), d2 = orient(p3, p4, p2);
  const d3 = orient(p1, p2, p3), d4 = orient(p1, p2, p4);
  if (d1 * d2 < 0 && d3 * d4 < 0) return true;
  if (d1 === 0 && onSeg(p1, p3, p4)) return true;
  if (d2 === 0 && onSeg(p2, p3, p4)) return true;
  if (d3 === 0 && onSeg(p3, p1, p2)) return true;
  if (d4 === 0 && onSeg(p4, p1, p2)) return true;
  return false;
};

const segsOfRing = (ring) => {
  const out = [];
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i], b = ring[(i + 1) % ring.length];
    if (a && b) out.push([a, b]);
  }
  return out;
};

/* self-intersection for an open ring, considering adjacency as legal */
const ringSelfIntersects = (ring) => {
  const segs = segsOfRing(ring);
  for (let i = 0; i < segs.length; i++) {
    for (let j = i + 1; j < segs.length; j++) {
      const adj = j === i + 1 || (i === 0 && j === segs.length - 1);
      if (adj) continue;
      if (segsIntersect(segs[i][0], segs[i][1], segs[j][0], segs[j][1])) return true;
    }
  }
  return false;
};

/* drop near-duplicate / collinear vertices to produce a cleaner ring */
const cleanRing = (ring) => {
  if (!ring || ring.length < 3) return ring;
  const MIN = 0.5; /* meters — keeps us inside the user's intent */
  let changed = true;
  let cur = ring.slice();
  while (changed && cur.length >= 3) {
    changed = false;
    for (let i = 0; i < cur.length; i++) {
      if (cur.length < 3) break;
      const prev = cur[(i - 1 + cur.length) % cur.length];
      const a = cur[i], next = cur[(i + 1) % cur.length];
      /* remove duplicates */
      if (distMeters(prev, a) < MIN || distMeters(a, next) < MIN) {
        cur.splice(i, 1);
        changed = true;
        break;
      }
      /* remove collinear vertex */
      if (orient(a, prev, next) === 0) {
        cur.splice(i, 1);
        changed = true;
        break;
      }
    }
  }
  return cur;
};

/* attempt to repair a self-intersecting ring by dropping one vertex at a time */
const repairRing = (ring) => {
  let best = ring;
  for (let i = 1; i < ring.length; i++) {
    const cand = ring.filter((_, j) => j !== i);
    if (cand.length >= 3 && !ringSelfIntersects(cand)) return cand;
  }
  return best;
};

const overlayKey = "select-poly-overlay";
const rawMapOf = (ref) => {
  if (!ref || !ref.current) return null;
  const c = ref.current;
  return (typeof c.getMap === "function" && c.getMap()) || c;
};


export default function SelectByPolygonPanel({ me, mapRef, config, onClose, onPanelWidth, panelWidth }) {
  const [drawing, setDrawing] = useState(false);
  const drawingRef = useRef(false);
  const [pts, setPts] = useState([]);
  const ptsRef = useRef([]);
  const [validMsg, setValidMsg] = useState("");
  const [validErr, setValidErr] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState("");
  const [result, setResult] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportMsg, setExportMsg] = useState("");
  const [selected, setSelected] = useState({});
  const pointsRef = useRef([]);
  const featuresRef = useRef([]);

  const layers = (config && config.layers) || [];
  const apiLayer = (t) => {
    const f = (config && config.api_layers && config.api_layers[t]) || t;
    return f;
  };

  useEffect(() => {
    if (layers.length && Object.keys(selected).length === 0) {
      const init = {};
      layers.forEach((l) => { init[l.table] = true; });
      setSelected(init);
    }
  }, [layers, selected]);

  /* ---------------- overlay management ---------------- */

  const ensureOverlay = useCallback(() => {
    const m = mapRef && rawMapOf(mapRef);
    if (!m) return;
    if (!m.getSource(overlayKey)) {
      m.addSource(overlayKey, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: overlayKey + "-line", type: "line", source: overlayKey,
        paint: { "line-color": "#4f46e5", "line-width": 2, "line-dasharray": [2, 2] },
      });
      m.addLayer({
        id: overlayKey + "-pts", type: "circle", source: overlayKey,
        paint: { "circle-radius": 1.5, "circle-color": "#4f46e5" },
      });
      m.addLayer({
        id: overlayKey + "-fill", type: "fill", source: overlayKey,
        paint: { "fill-color": "#4f46e5", "fill-opacity": 0.12 },
      });
    }
  }, [mapRef]);

  const updateOverlay = useCallback((openPts, closed) => {
    const m = mapRef && rawMapOf(mapRef);
    if (!m || !m.getSource(overlayKey)) return;
    const lineFeat = {
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: openPts },
    };
    const ptFeat = {
      type: "Feature",
      properties: {},
      geometry: { type: "MultiPoint", coordinates: openPts },
    };
    const feats = [lineFeat, ptFeat];
    if (closed && openPts.length >= 3) {
      feats.push({
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [[...openPts, openPts[0]]] },
      });
    }
    m.getSource(overlayKey).setData({ type: "FeatureCollection", features: feats });
  }, [mapRef]);

  const clearOverlay = useCallback(() => {
    const m = mapRef && rawMapOf(mapRef);
    if (m && m.getSource(overlayKey)) m.getSource(overlayKey).setData({ type: "FeatureCollection", features: [] });
  }, [mapRef]);

  /* ---------------- click-drawing ---------------- */

  const resetDrawing = useCallback(() => {
    setDrawing(false);
    drawingRef.current = false;
    ptsRef.current = [];
    setPts([]);
    setValidMsg("");
    setValidErr("");
    setSearchErr("");
    setResult(null);
    setExportMsg("");
    featuresRef.current = [];
    clearOverlay();
    if (mapRef && rawMapOf(mapRef)) rawMapOf(mapRef).getCanvas().style.cursor = "";
  }, [mapRef, clearOverlay]);

  const startDrawing = useCallback(() => {
    ensureOverlay();
    setDrawing(true);
    drawingRef.current = true;
    ptsRef.current = [];
    setPts([]);
    setValidMsg("");
    setValidErr("");
    setSearchErr("");
    setResult(null);
    setExportMsg("");
    featuresRef.current = [];
    updateOverlay([], false);
    if (mapRef && rawMapOf(mapRef)) rawMapOf(mapRef).getCanvas().style.cursor = "crosshair";
  }, [mapRef, ensureOverlay, updateOverlay]);

  const finishDrawing = useCallback(() => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    setDrawing(false);
    if (mapRef && rawMapOf(mapRef)) rawMapOf(mapRef).getCanvas().style.cursor = "";
    const ring = ptsRef.current.slice();
    if (ring.length < 3) {
      setValidErr("Need at least 3 vertices to form a polygon.");
      return;
    }
    const cleaned = cleanRing(ring);
    if (cleaned.length < 3) {
      setValidErr("Polygon collapsed during cleanup — draw a bigger polygon.");
      return;
    }
    if (ringSelfIntersects(cleaned)) {
      const repaired = repairRing(cleaned);
      if (!ringSelfIntersects(repaired)) {
        ptsRef.current = repaired;
        setPts(repaired);
        updateOverlay(repaired, true);
        setValidMsg("Polygon was self-intersecting — simplified automatically (auto-repaired).");
      } else {
        setValidErr("Polygon is self-intersecting and could not be repaired automatically. Cancel and redraw.");
        return;
      }
    } else {
      ptsRef.current = cleaned;
      setPts(cleaned);
      updateOverlay(cleaned, true);
      setValidMsg("Polygon closed with " + (cleaned.length) + " vertices.");
    }
  }, [mapRef, updateOverlay]);

  const onMapClick = useCallback((e) => {
    if (!drawingRef.current || !e || !e.lngLat) return;
    const p = [e.lngLat.lng, e.lngLat.lat];
    const last = ptsRef.current[ptsRef.current.length - 1];
    if (last && distMeters(last, p) < 1) return;
    ptsRef.current = [...ptsRef.current, p];
    setPts(ptsRef.current);
    updateOverlay(ptsRef.current, false);
  }, [mapRef, updateOverlay]);

  const onMapDblClick = useCallback((e) => {
    if (!drawingRef.current) return;
    e.preventDefault && e.preventDefault();
    finishDrawing();
  }, [mapRef, finishDrawing]);

  const undoLast = useCallback(() => {
    if (!drawingRef.current || !ptsRef.current.length) return;
    ptsRef.current = ptsRef.current.slice(0, -1);
    setPts(ptsRef.current);
    setValidErr("");
    updateOverlay(ptsRef.current, false);
  }, [updateOverlay]);

  /* wire map listeners only while drawing */
  useEffect(() => {
    const m = mapRef && rawMapOf(mapRef);
    if (!m) return;
    if (drawing) {
      m.on("click", onMapClick);
      m.on("dblclick", onMapDblClick);
      m.getCanvas().style.cursor = "crosshair";
    }
    return () => {
      m.off("click", onMapClick);
      m.off("dblclick", onMapDblClick);
    };
  }, [drawing, mapRef, onMapClick, onMapDblClick]);

  useEffect(() => () => clearOverlay(), [clearOverlay]);

  /* ---------------- search ---------------- */

  const runSearch = async () => {
    const ring = ptsRef.current;
    if (!ring || ring.length < 3) { setSearchErr("Close and validate a polygon first."); return; }
    const tables = layers.filter((l) => selected[l.table]).map((l) => l.table);
    if (!tables.length) { setSearchErr("Choose at least one layer."); return; }
    const geometry = { type: "Polygon", coordinates: [[...ring, ring[0]]] };
    setSearching(true);
    setSearchErr("");
    setExportMsg("");
    featuresRef.current = [];
    let total = 0;
    const perLayer = [];
    const shared = new Set();
    const bbox = [Infinity, Infinity, -Infinity, -Infinity];
    try {
      for (const t of tables) {
        let count = 0;
        try {
          const res = await axios.post(
            "/api/v1/analysis/intersect/" + apiLayer(t),
            { geometry },
            { headers: authHeaders() }
          );
          const feats = (res.data && res.data.features) || [];
          const seen = new Set();
          feats.forEach((f) => {
            const pr = (f && f.properties) || {};
            const key = pr.Req_Number || pr.id || JSON.stringify(pr);
            if (seen.has(key)) return;
            seen.add(key);
            shared.add(key);
            featuresRef.current.push(f);
            /* accumulate bbox over each found feature */
            const walk = (c) => {
              if (!c) return;
              if (typeof c[0] === "number") {
                if (c[0] < bbox[0]) bbox[0] = c[0];
                if (c[1] < bbox[1]) bbox[1] = c[1];
                if (c[0] > bbox[2]) bbox[2] = c[0];
                if (c[1] > bbox[3]) bbox[3] = c[1];
              } else c.forEach(walk);
            };
            walk(f.geometry && f.geometry.coordinates);
          });
          count = feats.length;
        } catch (err) {
          perLayer.push({ table: t, count: -1, error: (err && err.response && err.response.data && err.response.data.detail) || (err && err.message) || "failed" });
          continue;
        }
        total += count;
        perLayer.push({ table: t, count });
      }
      setResult({ total, layers: perLayer, bbox: isFinite(bbox[0]) ? bbox : null });
      if (total === 0) setResult({ total: 0, layers: perLayer, bbox: null });
    } catch (e) {
      setSearchErr((e && e.response && e.response.data && e.response.data.detail) || (e && e.message) || "Search failed");
    } finally {
      setSearching(false);
    }
  };

  const zoomToSelection = () => {
    const r = result;
    if (!r || !r.bbox) return;
    const m = mapRef && rawMapOf(mapRef);
    if (m) m.fitBounds([[r.bbox[0], r.bbox[1]], [r.bbox[2], r.bbox[3]]], { padding: 60, maxZoom: 17, duration: 1000 });
  };

  const downloadGeoJSON = async () => {
    if (!result || result.total === 0 || !featuresRef.current.length) return;
    setExporting(true);
    setExportMsg("");
    try {
      const blob = new Blob([
        JSON.stringify({ type: "FeatureCollection", features: featuresRef.current }, null, 2)
      ], { type: "application/geo+json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "polygon_selection.geojson";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setExportMsg("Exported " + featuresRef.current.length + " features as GeoJSON.");
    } catch (e) {
      setExportMsg("Export failed: " + ((e && e.message) || "unknown error"));
    } finally {
      setExporting(false);
    }
  };

  const toggleLayer = (t) => setSelected((s) => ({ ...s, [t]: !s[t] }));

  return (
    <div
      className="absolute top-[100px] left-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200 flex flex-col max-h-[calc(100vh-150px)]"
      style={{ width: panelWidth || 320 }}
    >
      <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100 flex-shrink-0">
        <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider flex items-center gap-1.5">
          <Layers className="w-3.5 h-3.5 text-indigo-600" /> Select by Polygon
        </h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-700"><X className="w-4 h-4" /></button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Step 1: draw */}
        <div className="border border-gray-200 rounded-lg p-3">
          {!drawing ? (
            <button onClick={startDrawing}
              className="w-full px-3 py-2 rounded-md text-xs font-bold bg-indigo-600 text-white hover:bg-indigo-700 flex items-center justify-center gap-1.5">
              <MousePointer2 className="w-3.5 h-3.5" /> Draw polygon
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-[11px] font-semibold text-gray-600 flex items-center gap-1.5">
                <MousePointer2 className="w-3.5 h-3.5 text-indigo-600" />
                Click on the map to add vertices
              </p>
              <p className="text-[11px] text-gray-500">
                <span className="font-bold text-indigo-700">{pts.length}</span> vertices · double-click to close
              </p>
              <div className="grid grid-cols-2 gap-1.5">
                <button onClick={undoLast}
                  className="px-2 py-1.5 rounded-md text-[11px] font-semibold bg-white border border-gray-300 text-gray-600 hover:bg-gray-50 flex items-center justify-center gap-1">
                  <Undo2 className="w-3 h-3" /> Undo last
                </button>
                <button onClick={resetDrawing}
                  className="px-2 py-1.5 rounded-md text-[11px] font-semibold bg-white border border-gray-300 text-red-600 hover:bg-red-50 flex items-center justify-center gap-1">
                  <X className="w-3 h-3" /> Cancel
                </button>
              </div>
              <button onClick={finishDrawing} disabled={pts.length < 3}
                className="w-full px-3 py-2 rounded-md text-xs font-bold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 flex items-center justify-center gap-1.5">
                <Check className="w-3.5 h-3.5" /> Close & validate polygon
              </button>
            </div>
          )}
          {validMsg && <p className="text-[11px] text-emerald-600 mt-2 flex items-start gap-1"><CheckCircle2 className="w-3 h-3 mt-0.5 flex-shrink-0" /> {validMsg}</p>}
          {validErr && <p className="text-[11px] text-red-600 mt-2 flex items-start gap-1"><AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" /> {validErr}</p>}
        </div>

        {/* Step 2: layers */}
        <div className="border border-gray-200 rounded-lg p-3">
          <p className="text-[11px] font-bold text-gray-600 mb-1.5">Layers to search</p>
          <div className="space-y-1.5 max-h-40 overflow-y-auto">
            {layers.map((l) => (
              <label key={l.table} className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
                <input type="checkbox" checked={!!selected[l.table]}
                  onChange={() => toggleLayer(l.table)}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
                <span className="flex-1">{l.label || l.table}</span>
                {l.geom && <span className="text-[10px] text-gray-400">{l.geom}</span>}
              </label>
            ))}
          </div>
        </div>

        {/* Step 3: run */}
        <button onClick={runSearch} disabled={searching || pts.length < 3}
          className="w-full px-3 py-2.5 rounded-md text-xs font-bold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-1.5">
          {searching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ZoomIn className="w-3.5 h-3.5" />}
          Find features in polygon
        </button>
        {searchErr && <p className="text-[11px] text-red-600 flex items-start gap-1"><AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" /> {searchErr}</p>}

        {/* Results */}
        {result && (
          <div className="border border-gray-200 rounded-lg p-3 space-y-2">
            {result.total > 0 ? (
              <p className="text-[11px] font-bold text-emerald-600">
                {result.total} feature{result.total === 1 ? "" : "s"} found within this area.
              </p>
            ) : (
              <p className="text-[11px] text-gray-500">No features found within this area.</p>
            )}
            <div className="space-y-1">
              {result.layers.map((r) => (
                <div key={r.table} className="flex items-center justify-between text-[11px]">
                  <span className="text-gray-600">{r.table}</span>
                  {r.count < 0
                    ? <span className="text-red-500 text-[10px]">{r.error}</span>
                    : <span className="font-semibold text-gray-700">{r.count}</span>}
                </div>
              ))}
            </div>
            {result.total > 0 && (
              <div className="grid grid-cols-2 gap-1.5 pt-1 border-t border-gray-100">
                <button onClick={zoomToSelection}
                  className="px-2 py-1.5 rounded-md text-[11px] font-semibold bg-white border border-gray-300 text-gray-600 hover:bg-gray-50 flex items-center justify-center gap-1">
                  <ZoomIn className="w-3 h-3" /> Zoom
                </button>
                <button onClick={downloadGeoJSON} disabled={exporting}
                  className="px-2 py-1.5 rounded-md text-[11px] font-semibold bg-white border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-50 flex items-center justify-center gap-1">
                  {exporting ? <Loader2 className="w-3 h-3 animate-spin" /> : <FolderOutput className="w-3 h-3" />} Export
                </button>
              </div>
            )}
            <button onClick={startDrawing}
              className="w-full px-3 py-1.5 rounded-md text-[11px] font-semibold text-gray-500 hover:bg-gray-100 flex items-center justify-center gap-1">
              <RefreshCw className="w-3 h-3" /> Redraw polygon
            </button>
          </div>
        )}
        {exportMsg && <p className="text-[11px] text-gray-600">{exportMsg}</p>}
      </div>
    </div>
  );
}
