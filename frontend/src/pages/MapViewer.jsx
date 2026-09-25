import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import Map, { Popup, Marker, useControl } from "react-map-gl/maplibre";
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import "maplibre-gl/dist/maplibre-gl.css";
import axios from "axios";
import { Search, UploadCloud, AlertCircle, X, PenTool, Trash2, Layers, Map as MapIcon, Table, Filter, MapPin, ZoomIn, Plus, Minus, Maximize, Download, Type, GripVertical, ChevronUp, ChevronDown, Ruler, DatabaseZap, ScanLine, Printer } from "lucide-react";
import UpdateGeometryPanel from "../components/UpdateGeometryPanel";
import SelectByPolygonPanel from "../components/SelectByPolygonPanel";
import PrintLayoutPanel from "../components/PrintLayoutPanel";
import MapLegendPanel from "../components/MapLegendPanel";

const BASEMAPS = {
  carto: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  osm: {
    version: 8,
    sources: { osm: { type: "raster", tiles: ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "&copy; OpenStreetMap Contributors" } },
    layers: [{ id: "osm", type: "raster", source: "osm", minzoom: 0, maxzoom: 22 }]
  },
  satellite: {
    version: 8,
    sources: { google: { type: "raster", tiles: ["https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"], tileSize: 256, attribution: "&copy; Google" } },
    layers: [{ id: "google", type: "raster", source: "google", minzoom: 0, maxzoom: 22 }]
  },
  none: {
    version: 8,
    sources: {},
    layers: [{ id: "bg", type: "background", paint: { "background-color": "#f0f0f0" } }]
  }
};

// --- Client-side geodesic measurement (no turf dependency) ---
const EARTH_RADIUS_M = 6371008.8; // WGS84 mean radius (m)
const FEDDAN_SQM = 4200.83; // 1 feddan = 4200.83 m² (administrative convention used across the app)
const DEG2RAD = (d) => (d * Math.PI) / 180;
const haversineMeters = (a, b) => {
  const dLat = DEG2RAD(b[1] - a[1]);
  const dLng = DEG2RAD(b[0] - a[0]);
  const s = Math.sin(dLat / 2) ** 2 +
            Math.cos(DEG2RAD(a[1])) * Math.cos(DEG2RAD(b[1])) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(s)));
};
// Turf-equivalent geodesic polygon area in m² (ring of [lng,lat]; lng in decimal degrees).
const geodesicAreaSqm = (ring) => {
  let total = 0;
  for (let i = 0; i < ring.length; i++) {
    const p1 = ring[i];
    const p2 = ring[(i + 1) % ring.length];
    total += (DEG2RAD(p2[0]) - DEG2RAD(p1[0])) *
             (2 + Math.sin(DEG2RAD(p1[1])) + Math.sin(DEG2RAD(p2[1])));
  }
  return Math.abs((total * EARTH_RADIUS_M * EARTH_RADIUS_M) / 2);
};
const measureLengthMeters = (coords) => {
  let m = 0;
  for (let i = 1; i < coords.length; i++) m += haversineMeters(coords[i - 1], coords[i]);
  return m;
};
// Closed-ring sides (handles duplicate closing vertex) -> [{ mid, meters }]
const ringSegments = (ring) => {
  if (!ring || ring.length < 3) return [];
  let pts = ring;
  const first = pts[0], last = pts[pts.length - 1];
  if (first[0] === last[0] && first[1] === last[1]) pts = pts.slice(0, -1);
  const n = pts.length;
  if (n < 2) return [];
  const segs = [];
  for (let i = 0; i < n; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % n];
    segs.push({ meters: haversineMeters(a, b), mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] });
  }
  return segs;
};
// Area-weighted centroid (falls back to vertex average for degenerate rings).
const polygonCentroid = (ring) => {
  if (!ring || !ring.length) return null;
  let pts = ring;
  const first = pts[0], last = pts[pts.length - 1];
  if (first[0] === last[0] && first[1] === last[1]) pts = pts.slice(0, -1);
  const n = pts.length;
  if (!n) return null;
  let fSum = 0, cx = 0, cy = 0;
  for (let i = 0; i < n; i++) {
    const x0 = pts[i][0], y0 = pts[i][1];
    const x1 = pts[(i + 1) % n][0], y1 = pts[(i + 1) % n][1];
    const f = x0 * y1 - x1 * y0;
    fSum += f;
    cx += (x0 + x1) * f;
    cy += (y0 + y1) * f;
  }
  if (Math.abs(fSum) < 1e-12) {
    let sx = 0, sy = 0;
    for (const p of pts) { sx += p[0]; sy += p[1]; }
    return [sx / n, sy / n];
  }
  return [cx / (3 * fSum), cy / (3 * fSum)];
};
const formatArea = (sqm, unit) => {
  if (unit === 'sqkm') return (sqm / 1000000).toLocaleString('en-US', { maximumFractionDigits: 4 }) + ' km²';
  if (unit === 'feddan') return (sqm / FEDDAN_SQM).toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' feddan';
  if (unit === 'sqm') return sqm.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' m²';
  if (sqm >= 1000000) return (sqm / 1000000).toLocaleString('en-US', { maximumFractionDigits: 4 }) + ' km²';
  if (sqm >= FEDDAN_SQM) return (sqm / FEDDAN_SQM).toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' feddan';
  return sqm.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' m²';
};
// Returns { type: "length", meters } for LineString or { type: "area", sqm } for Polygon.
const segmentsWithMidpoints = (coords) => {
  const segs = [];
  for (let i = 1; i < coords.length; i++) {
    const a = coords[i - 1];
    const b = coords[i];
    segs.push({ meters: haversineMeters(a, b), mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] });
  }
  return segs;
};
const formatLength = (meters, unit) => {
  if (unit === 'km') return (meters / 1000).toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' km';
  if (unit === 'm') return meters.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' m';
  return meters >= 1000
    ? (meters / 1000).toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' km'
    : meters.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' m';
};
const measureGeom = (geometry) => {
  if (!geometry || !geometry.coordinates) return null;
  if (geometry.type === "LineString") return { type: "length", meters: measureLengthMeters(geometry.coordinates) };
  if (geometry.type === "Polygon") {
    const ring = geometry.coordinates[0] || [];
    if (ring.length < 4) return null;
    return { type: "area", sqm: geodesicAreaSqm(ring) };
  }
  return null;
};

function DrawControl(props) {
  const propsRef = React.useRef(props);
  propsRef.current = props;
  const cleanupRef = React.useRef(null);
  const draw = useControl(
    () => new MapboxDraw(props),
    ({ map }) => {
      const onCreate = (e) => propsRef.current.onDrawCreate && propsRef.current.onDrawCreate(e);
      const onUpdate = (e) => propsRef.current.onDrawUpdate && propsRef.current.onDrawUpdate(e);
      const onDelete = (e) => propsRef.current.onDrawDelete && propsRef.current.onDrawDelete(e);
      const onRender = (e) => propsRef.current.onDrawRender && propsRef.current.onDrawRender(e);
      map.on('draw.create', onCreate);
      map.on('draw.update', onUpdate);
      map.on('draw.delete', onDelete);
      map.on('draw.render', onRender);
      cleanupRef.current = () => {
        map.off('draw.create', onCreate);
        map.off('draw.update', onUpdate);
        map.off('draw.delete', onDelete);
        map.off('draw.render', onRender);
      };
    },
    () => {
      if (cleanupRef.current) cleanupRef.current();
    },
    {
      position: props.position
    }
  );
  
  React.useEffect(() => {
    if (props.onInit) {
      props.onInit(draw);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draw]);
  
  return null;
}

const TOPOLOGY_TABLE = "lands";
const MVT_NAME = { lands: "land", eshghalat: "eshghalat", points: "point" };

// UI layer key (config table name) -> real PostGIS table used by the API
const apiLayer = (k) => k;

// [minLng, minLat, maxLng, maxLat] of any GeoJSON geometry (or null).
const geomBounds = (geometry) => {
  if (!geometry || !geometry.coordinates) return null;
  let minx = 180, miny = 90, maxx = -180, maxy = -90;
  const eat = (x, y) => {
    if (Number.isFinite(x) && Number.isFinite(y)) {
      if (x < minx) minx = x;
      if (y < miny) miny = y;
      if (x > maxx) maxx = x;
      if (y > maxy) maxy = y;
    }
  };
  const walk = (c) => {
    if (!c) return;
    if (typeof c[0] === "number") eat(c[0], c[1]);
    else c.forEach(walk);
  };
  walk(geometry.coordinates);
  return minx <= maxx ? [minx, miny, maxx, maxy] : null;
};

// rows endpoint returns [{name,type}]; tolerate a plain-string list too.
const normCols = (cols) =>
  Array.isArray(cols)
    ? cols.map((c) => (typeof c === "string" ? { name: c, type: "text" } : { name: c && c.name, type: (c && c.type) || "text" }))
    : [];

// Default widths (px) matching the previous fixed Tailwind classes.
const PANEL_DEFAULTS = { search: 384, layers: 288, export: 288, location: 288, query: 288, basemap: 192, upload: 256, measure: 288, table: 416, topology: 320, update: 440, polygon: 400, print: 400 };

// Vertical resize grip used by every floating panel. `anchor` = "left" anchors
// the panel's left edge (grows rightward on drag), "right" anchors the right edge.
function ResizeHandle({ anchor, width, min, max, onWidth }) {
  const start = useRef(null);
  const onPointerDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    start.current = { x: e.clientX, w: width };
    const move = (ev) => {
      if (!start.current) return;
      const dx = ev.clientX - start.current.x;
      const next = anchor === "left" ? start.current.w + dx : start.current.w - dx;
      onWidth(Math.max(min, Math.min(max, next)));
    };
    const up = () => {
      start.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const side = anchor === "left" ? "right-0" : "left-0";
  return (
    <div
      onPointerDown={onPointerDown}
      className={"absolute " + side + " inset-y-0 w-1.5 cursor-ew-resize select-none flex items-center justify-center group"}
      title="Drag to resize"
      style={{ touchAction: "none" }}
    >
      <div className="w-[3px] h-10 rounded-full bg-gray-300/70 group-hover:bg-blue-500 transition-colors" />
    </div>
  );
}

export default function MapViewer({ me }) {
  const isEditor = !!(me && (me.role === "admin" || me.role === "editor" || (me.permissions || []).includes("edit_geometry")));
  const mapRef = useRef();
  const mapApiRef = useRef(null); // maplibre instance, captured on 'load'

  // Layers come from the admin-curated map_layers table (any logged-in user).
  const [layersCfg, setLayersCfg] = useState([]); // [{table,label,color,gtype,label_field}]
  const [configLoaded, setConfigLoaded] = useState(false);
  const [prefsLoaded, setPrefsLoaded] = useState(false);
  const [mapReady, setMapReady] = useState(false);

  // Resizable floating-panel widths (per panel key, px).
  const [panelWidths, setPanelWidths] = useState({});
  const setPanelWidth = useCallback((key, w) => setPanelWidths((p) => ({ ...p, [key]: w })), []);
  const pw = (key) => panelWidths[key] ?? PANEL_DEFAULTS[key];

  const layerByTable = useCallback((t) => layersCfg.find((l) => l.table === t), [layersCfg]);
  const layerLabel = (t) => { const c = layerByTable(t); return c ? c.label : t; };
  const layerColor = (t) => { const c = layerByTable(t); return c ? c.color : "#3388ff"; };
  const mvtName = (t) => MVT_NAME[t] || t;
  const isPointLike = (g) => /POINT/.test(g || "");
  const isLineLike = (g) => /LINE/.test(g || "");

  const [layerVisibility, setLayerVisibility] = useState({});
  const [layerStyle, setLayerStyle] = useState({});
  const [layerOrder, setLayerOrder] = useState([]);
  const [dragKey, setDragKey] = useState(null);
  const orderedMeta = [...layersCfg].sort((a, b) => layerOrder.indexOf(a.table) - layerOrder.indexOf(b.table));
  const allOn = useMemo(() => Object.fromEntries(layersCfg.map((l) => [l.table, true])), [layersCfg]);
  const allOff = useMemo(() => Object.fromEntries(layersCfg.map((l) => [l.table, false])), [layersCfg]);
  const dropOnLayer = (targetKey) => {
    if (!dragKey || dragKey === targetKey) return;
    const next = layerOrder.filter((k) => k !== dragKey);
    next.splice(next.indexOf(targetKey), 0, dragKey);
    setLayerOrder(next);
    setDragKey(null);
  };
const moveLayer = (key, dir) => {
    const i = layerOrder.indexOf(key);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= layerOrder.length) return;
    const next = [...layerOrder];
    next.splice(i, 1);
    next.splice(j, 0, key);
    setLayerOrder(next);
  };
  const toggleLegend = () => setLegendExpanded((v) => {
    const nv = !v;
    try { localStorage.setItem("mapLegendExpanded", nv ? "1" : "0"); } catch (e) { /* ignore */ }
    return nv;
  });
  // Dynamic vector sources/layers are added imperatively to the loaded map
  // (react-map-gl JSX <Source>/<Layer> children get dropped during style
  // rebuilds, so only the first layer would survive).
  const dynRef = useRef({ sources: [], layers: [] });
  // react-map-gl v8 exposes the raw maplibre instance via ref.getMap();
  // the proxy ref omits add/removeSource/Layer, paint & layout setters.
  const rawMap = () => {
    const a = mapApiRef.current;
    if (a) return (typeof a.getMap === "function" && a.getMap()) || a;
    const r = mapRef.current;
    if (r) return (typeof r.getMap === "function" && r.getMap()) || r;
    return null;
  };
  const clearDynamic = (map = rawMap()) => {
    if (!map || typeof map.removeLayer !== "function") return;
    [...dynRef.current.layers].forEach((id) => { if (map.getLayer(id)) map.removeLayer(id); });
    [...dynRef.current.sources].forEach((id) => { if (map.getSource(id)) map.removeSource(id); });
    dynRef.current = { sources: [], layers: [] };
  };
  const addDyn = (map, id, spec) => {
    if (!map || typeof map.addLayer !== "function") return;
    if (!dynRef.current.layers.includes(id)) dynRef.current.layers.push(id);
    if (map.getLayer(id)) return;
    map.addLayer({ id, ...spec });
  };
  const addSrc = (map, id, spec) => {
    if (!map || typeof map.addSource !== "function") return;
    if (!dynRef.current.sources.includes(id)) dynRef.current.sources.push(id);
    if (map.getSource(id)) return;
    map.addSource(id, spec);
  };
  const buildDynamic = (map = rawMap()) => {
    if (!map || typeof map.addSource !== "function") return;
    clearDynamic(map);
    layerOrder.forEach((k) => {
      const cfg = layerByTable(k);
      if (!cfg) return;
      const sname = mvtName(cfg.table);
      const style = layerStyle[cfg.table] || { color: cfg.color || "#3388ff", opacity: 0.5 };
      const vis = layerVisibility[cfg.table] ? "visible" : "none";
      const url = `/api/v1/layers/${apiLayer(cfg.table)}/tiles/{z}/{x}/{y}.pbf?token=${authToken}${selection && selection.id ? `&sel=${selection.id}` : ""}`;
      addSrc(map, k, { type: "vector", tiles: [url], minzoom: 0, maxzoom: 22 });
      if (isPointLike(cfg.gtype)) {
        addDyn(map, `${k}-circle`, { source: k, "source-layer": sname, type: "circle", paint: { "circle-radius": 5, "circle-color": style.color, "circle-opacity": style.opacity, "circle-stroke-width": 1, "circle-stroke-color": "#fff" }, layout: { visibility: vis } });
      } else if (isLineLike(cfg.gtype)) {
        addDyn(map, `${k}-line`, { source: k, "source-layer": sname, type: "line", paint: { "line-color": style.color, "line-opacity": style.opacity, "line-width": 2 }, layout: { visibility: vis } });
      } else {
        addDyn(map, `${k}-fill`, { source: k, "source-layer": sname, type: "fill", paint: { "fill-color": style.color, "fill-opacity": style.opacity }, layout: { visibility: vis } });
        addDyn(map, `${k}-casing`, { source: k, "source-layer": sname, type: "line", paint: { "line-color": "#ffffff", "line-width": 4, "line-opacity": 0.9 }, layout: { visibility: vis } });
        addDyn(map, `${k}-line`, { source: k, "source-layer": sname, type: "line", paint: { "line-color": style.color, "line-opacity": style.opacity, "line-width": 2 }, layout: { visibility: vis } });
      }
      if (labelLayers[cfg.table]) {
        addDyn(map, `${k}-label`, { source: k, "source-layer": sname, type: "symbol", minzoom: 14, layout: { "text-field": ["get", cfg.label_field || "Req_Number"], "text-size": 11, "text-anchor": "center" }, paint: { "text-color": "#1e293b", "text-halo-color": "#ffffff", "text-halo-width": 1.5 } });
      }
    });
    if (searchResults && searchResults.features && searchResults.features.length) {
      addSrc(map, "search-results", { type: "geojson", data: searchResults });
      addDyn(map, "search-highlight", { source: "search-results", type: "line", paint: { "line-color": "#f1c40f", "line-width": 4 } });
    }
    if (uploadPreview && uploadPreview.features && uploadPreview.features.length) {
      addSrc(map, "upload-preview", { type: "geojson", data: uploadPreview });
      addDyn(map, "upl-fill", { source: "upload-preview", type: "fill", paint: { "fill-color": "#f39c12", "fill-opacity": 0.5 } });
      addDyn(map, "upl-line", { source: "upload-preview", type: "line", paint: { "line-color": "#e67e22", "line-width": 2 } });
      addDyn(map, "upl-circle", { source: "upload-preview", type: "circle", paint: { "circle-radius": 5, "circle-color": "#f39c12", "circle-stroke-width": 1, "circle-stroke-color": "#fff" } });
    }
  };
  const layerStats = (k) => {
    const st = serverStats[k];
    if (!st) return { count: 0, areaText: "Loading..." };
    const area = Number(st.total_area_sqm) || 0;
    return {
      count: st.count || 0,
      areaText: area > 0
        ? area.toLocaleString("en-US", { maximumFractionDigits: 0 }) + " m² (" + Number(st.total_area_feddan || 0).toFixed(2) + " feddan)"
        : "No area values",
    };
  };
  // Legend reflects whatever the map is actually showing: a layer is listed
  // only if its tiles contain at least one feature in the current viewport.
  const legendTimer = useRef(null);
  const legendViewRef = useRef(() => {});
  const updateLegendFromView = () => {
    const map = rawMap();
    if (!map || typeof map.querySourceFeatures !== "function") return;
    const shown = [];
    layerOrder.forEach((k) => {
      const cfg = layerByTable(k);
      if (!cfg || !layerVisibility[k]) return;
      try {
        const ftrs = map.querySourceFeatures(k, { sourceLayer: mvtName(cfg.table) });
        if (ftrs && ftrs.length > 0) shown.push(k);
      } catch (e) { /* source not ready yet */ }
    });
    setLegendViewTables(shown);
  };
  legendViewRef.current = updateLegendFromView;
  const scheduleLegendView = () => {
    if (legendTimer.current) clearTimeout(legendTimer.current);
    legendTimer.current = setTimeout(() => legendViewRef.current(), 250);
  };
  const [basemap, setBasemap] = useState(() => localStorage.getItem("preferredBasemap") || "carto");
  
  useEffect(() => {
    localStorage.setItem("preferredBasemap", basemap);
  }, [basemap]);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [selectedFeature, setSelectedFeature] = useState(null);
  const [cursor, setCursor] = useState(null);
  const [mapZoom, setMapZoom] = useState(11);
  const [tileAuthError, setTileAuthError] = useState(false);
  const [topologyResults, setTopologyResults] = useState(null);
  const [uploadStatus, setUploadStatus] = useState(null);
  const [uploadPreview, setUploadPreview] = useState(null);
  const [uploadFileName, setUploadFileName] = useState(null);
  const [activeTool, setActiveTool] = useState(null);
  const [legendViewTables, setLegendViewTables] = useState(null);
  const [legendExpanded, setLegendExpanded] = useState(() => {
    try {
      const v = localStorage.getItem("mapLegendExpanded");
      return v === null ? true : v === "1";
    } catch (e) { return true; }
  });
  const [drawInstance, setDrawInstance] = useState(null);
  const [activeTable, setActiveTable] = useState(null); // default filled from config
  const [tableLocked, setTableLocked] = useState(null); // layer key when opened from Layers panel
  const [tableFilter, setTableFilter] = useState("");
  const [searchMatches, setSearchMatches] = useState([]);
  const [labelLayers, setLabelLayers] = useState({});
  const [exportLayers, setExportLayers] = useState({});
  const [exportFormat, setExportFormat] = useState("geojson");
  const [exporting, setExporting] = useState(null);
  const [exportError, setExportError] = useState(null);
  const [locationLayer, setLocationLayer] = useState(null);
  const [drawnGeom, setDrawnGeom] = useState(null);
  const [overlapPairs, setOverlapPairs] = useState(null); // null = not run yet
  const [overlapInvalid, setOverlapInvalid] = useState(null);
  const [overlapBusy, setOverlapBusy] = useState(false);
  const [overlapErr, setOverlapErr] = useState("");
  const [measureMode, setMeasureMode] = useState("length"); // 'length' | 'area'
  const [measureResult, setMeasureResult] = useState(null); // measureGeom result
  const [measureUnit, setMeasureUnit] = useState("auto"); // length: auto|m|km | area: auto|sqm|sqkm|feddan
  const [measureSegs, setMeasureSegs] = useState([]); // [{ mid:[lng,lat], meters }]
  const [queryLayer, setQueryLayer] = useState(null);
  const [queryField, setQueryField] = useState("Req_Number");
  const [queryOp, setQueryOp] = useState("contains");
  const [queryValue, setQueryValue] = useState("");
  const [queryConds, setQueryConds] = useState([]);
  const [layerCols, setLayerCols] = useState({}); // table -> [{name,type}] from rows responses
  // Read once per mount.
  const [authToken] = useState(() => {
    try {
      return localStorage.getItem("token") || "";
    } catch (e) {
      return "";
    }
  });
  const [selection, setSelection] = useState(null); // {id, layer, count, bbox, sample} from server
  const [serverStats, setServerStats] = useState({});
  const [tableRows, setTableRows] = useState({ items: [], total: 0, columns: [] });
  const [tablePage, setTablePage] = useState(0);
  const [debouncedFilter, setDebouncedFilter] = useState("");
  const TABLE_PAGE_SIZE = 100;
  const authHeaders = () => ({ Authorization: "Bearer " + localStorage.getItem("token") });
  const deleteSelection = async () => {
    if (selection && selection.id) {
      try {
        await axios.delete(`/api/v1/layers/selections/${selection.id}`, { headers: authHeaders() });
      } catch (e) { /* expired already */ }
    }
    setSelection(null);
  };

  // Rebuild dynamic sources/layers after the base style loads, and whenever
  // the layer set/order/basemap/selection/search/preview changes.
  useEffect(() => {
    if (!mapReady || !configLoaded) return;
    buildDynamic();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapReady, configLoaded, layerOrder, selection && selection.id, basemap, searchResults, uploadPreview]);
  // Keep paint + visibility + labels in sync without rebuilding sources.
  useEffect(() => {
    if (!mapReady || !configLoaded) return;
    const map = rawMap();
    if (!map || typeof map.setPaintProperty !== "function") return;
    layerOrder.forEach((k) => {
      const cfg = layerByTable(k);
      if (!cfg) return;
      const style = layerStyle[cfg.table] || { color: cfg.color || "#3388ff", opacity: 0.5 };
      const vis = layerVisibility[cfg.table] ? "visible" : "none";
      const ids = isPointLike(cfg.gtype) ? [`${k}-circle`] : isLineLike(cfg.gtype) ? [`${k}-line`] : [`${k}-fill`, `${k}-casing`, `${k}-line`];
      ids.forEach((id) => {
        if (!map.getLayer(id)) return;
        map.setLayoutProperty(id, "visibility", vis);
        if (id.endsWith("-fill")) {
          map.setPaintProperty(id, "fill-color", style.color);
          map.setPaintProperty(id, "fill-opacity", style.opacity);
        } else if (id.endsWith("-circle")) {
          map.setPaintProperty(id, "circle-color", style.color);
          map.setPaintProperty(id, "circle-opacity", style.opacity);
        } else if (id.endsWith("-casing")) {
          // white casing stays white
        } else {
          map.setPaintProperty(id, "line-color", style.color);
          map.setPaintProperty(id, "line-opacity", style.opacity);
        }
      });
      const lid = `${k}-label`;
      const on = labelLayers[cfg.table] === true;
      if (on && !map.getLayer(lid)) {
        map.addLayer({ id: lid, source: k, "source-layer": mvtName(cfg.table), type: "symbol", minzoom: 14, layout: { "text-field": ["get", cfg.label_field || "Req_Number"], "text-size": 11, "text-anchor": "center" }, paint: { "text-color": "#1e293b", "text-halo-color": "#ffffff", "text-halo-width": 1.5 } });
      } else if (!on && map.getLayer(lid)) {
        map.removeLayer(lid);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapReady, configLoaded, layerOrder, layerStyle, layerVisibility, labelLayers]);

  // Re-scan the map view for legend entries whenever the visible layer set
  // or the selection (which retiles dynamic sources) changes.
  useEffect(() => {
    if (!mapReady || !configLoaded) return;
    scheduleLegendView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapReady, configLoaded, layerOrder, layerVisibility, selection && selection.id]);

  const QUERY_FIELDS = [
    { key: "Req_Number", label: "Request No", type: "text" },
    { key: "Owner_Name", label: "Owner", type: "text" },
    { key: "Layer_Type", label: "Layer Type", type: "text" },
    { key: "Area_SQM", label: "Area (m²)", type: "number" },
    { key: "Area_Feddan", label: "Area (feddan)", type: "number" },
    { key: "created_by", label: "Added by", type: "text" },
    { key: "created_at", label: "Added on", type: "date" },
  ];
  const QUERY_OPS = {
    text: [["contains", "contains"], ["=", "="], ["!=", "≠"]],
    number: [["=", "="], ["!=", "≠"], [">", ">"], ["<", "<"], [">=", ">="], ["<=", "<="]],
    date: [[">=", "on/after"], ["<=", "on/before"], ["=", "on"]],
  };
  const pgTypeOf = (t) =>
    (["integer", "bigint", "smallint", "real", "double precision", "numeric", "decimal", "serial", "bigserial", "smallserial"].includes(t)) ? "number"
    : (["date", "timestamp without time zone", "timestamp with time zone", "timestamp", "timestamptz"].includes(t)) ? "date"
    : "text";
  const fieldTypeMap = useMemo(() => {
    const m = {};
    QUERY_FIELDS.forEach((f) => { m[f.key] = f.type; });
    Object.values(layerCols).forEach((cols) =>
      cols.forEach((c) => {
        if (m[c.name] === undefined) m[c.name] = pgTypeOf(c.type);
      }));
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layerCols]);
  const fieldTypeOf = (key) => fieldTypeMap[key] || "text";
  const queryFields = useMemo(() => {
    const known = layerCols[queryLayer];
    if (!known || !known.length) return QUERY_FIELDS;
    const names = new Set(known.map((c) => c.name));
    const matched = QUERY_FIELDS.filter((f) => names.has(f.key));
    const extra = known
      .filter((c) => c.name !== "id" && !QUERY_FIELDS.some((f) => f.key === c.name))
      .map((c) => ({ key: c.name, label: c.name, type: fieldTypeMap[c.name] }));
    return [...matched, ...extra];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryLayer, layerCols, fieldTypeMap]);
  const applyQuery = async () => {
    if (queryConds.length === 0 || !queryLayer) return;
    try {
      const res = await axios.post(`/api/v1/layers/${apiLayer(queryLayer)}/select`, {
        conds: queryConds.map((c) => ({ field: c.field, op: c.op, value: c.value })),
      }, { headers: authHeaders() });
      const d = res.data;
      setSelection({ id: d.selection_id, layer: queryLayer, count: d.count, bbox: d.bbox, sample: d.sample || [] });
      if (d.bbox && mapRef.current) {
        try { mapRef.current.fitBounds([[d.bbox[0], d.bbox[1]], [d.bbox[2], d.bbox[3]]], { padding: 60, duration: 1200 }); } catch (e) {}
      }
    } catch (err) {
      console.error("Select failed", err);
    }
  };
  const clearQuery = async () => {
    setQueryConds([]);
    await deleteSelection();
  };

  const featureCenter = (feature) => {
    let minx = 180, miny = 90, maxx = -180, maxy = -90;
    const eat = (x, y) => {
      if (Number.isFinite(x) && Number.isFinite(y)) {
        if (x < minx) minx = x;
        if (y < miny) miny = y;
        if (x > maxx) maxx = x;
        if (y > maxy) maxy = y;
      }
    };
    const walk = (c) => {
      if (!c) return;
      if (typeof c[0] === "number") eat(c[0], c[1]);
      else c.forEach(walk);
    };
    if (feature.geometry) walk(feature.geometry.coordinates);
    if (minx > maxx) return null;
    return [(minx + maxx) / 2, (miny + maxy) / 2];
  };
  const zoomToLayer = (key) => {
    const bb = serverStats[key] && serverStats[key].bbox;
    if (!bb || !mapRef.current) return;
    try {
      mapRef.current.fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]], { padding: 60, duration: 1200 });
    } catch (e) {}
  };
  const zoomToItem = (item) => {
    const props = {};
    Object.keys(item || {}).forEach((k) => { if (k !== "bbox") props[k] = item[k]; });
    if (item.bbox && mapRef.current) {
      try {
        mapRef.current.fitBounds([[item.bbox[0], item.bbox[1]], [item.bbox[2], item.bbox[3]]], { padding: 80, duration: 1000 });
      } catch (e) {}
      setSelectedFeature({
        longitude: (item.bbox[0] + item.bbox[2]) / 2,
        latitude: (item.bbox[1] + item.bbox[3]) / 2,
        properties: props, layer: null,
      });
    }
  };
  const zoomToFeature = (feature, zoom) => {
    const center = featureCenter(feature);
    if (!center || !mapRef.current) return;
    mapRef.current.flyTo({ center, zoom: zoom || 17 });
    setSelectedFeature({ longitude: center[0], latitude: center[1], properties: feature.properties, layer: null });
  };
  const fittedRef = useRef(false);
  const unionBB = (bbs) => [
    Math.min(...bbs.map((b) => b[0])),
    Math.min(...bbs.map((b) => b[1])),
    Math.max(...bbs.map((b) => b[2])),
    Math.max(...bbs.map((b) => b[3])),
  ];

  // Fly to the union of loaded layer extents (used for initial fit + zoom-extend)
  const zoomExtend = () => {
    if (!mapRef.current) return;
    const bbs = layersCfg.map((l) => serverStats[l.table] && serverStats[l.table].bbox).filter(Boolean);
    if (!bbs.length) return;
    try {
      const bb = unionBB(bbs);
      mapRef.current.fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]], { padding: 60, duration: 1200 });
    } catch (e) { /* map not ready */ }
  };

  const loadStats = async (selId) => {
    const keys = layersCfg.map((l) => l.table);
    if (!keys.length) return null;
    try {
      const params = selId ? { sel: selId } : {};
      const results = await Promise.all(keys.map((k) =>
        axios.get(`/api/v1/layers/${apiLayer(k)}/stats`, { headers: authHeaders(), params })));
      const stats = Object.fromEntries(keys.map((k, i) => [k, results[i].data]));
      setServerStats(stats);
      return stats;
    } catch (err) {
      console.error("Failed to load stats", err);
      return null;
    }
  };
  const fitStatsOnce = (stats) => {
    if (fittedRef.current || !mapRef.current || !stats) return;
    const bbs = layersCfg.map((l) => stats[l.table] && stats[l.table].bbox).filter(Boolean);
    if (!bbs.length) return;
    fittedRef.current = true;
    try {
      const bb = unionBB(bbs);
      mapRef.current.fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]], { padding: 60, duration: 1200 });
    } catch (e) { fittedRef.current = false; }
  };

  // Load curated visible layers once on mount, then overlay the user's own
  // saved preferences (color/opacity/visibility/order/labels/basemap) on top.
  useEffect(() => {
    let cancelled = false;
    const hdr = authHeaders();
    (async () => {
      try {
        const visRes = await axios.get("/api/v1/admin/db/map-layers/visible", { headers: hdr });
        if (cancelled) return;
        const ls = visRes.data.layers || [];
        setLayersCfg(ls);
        const keys = ls.map((l) => l.table);

        let pf = {};
        try {
          const pRes = await axios.get("/api/v1/prefs", { headers: hdr });
          pf = (pRes.data && pRes.data.data) || {};
        } catch (e) { /* prefs unavailable -> defaults */ }

        const pl = (pf.layers && typeof pf.layers === "object") ? pf.layers : {};
        const baseStyle = Object.fromEntries(keys.map((k) => {
          const c = ls.find((l) => l.table === k);
          return [k, { color: c.color || "#3388ff", opacity: isPointLike(c.gtype) ? 0.8 : 0.5 }];
        }));
        const vis = {};
        const style = {};
        const labels = {};
        keys.forEach((k) => {
          const p = pl[k] || {};
          vis[k] = typeof p.visible === "boolean" ? p.visible : true;
          style[k] = {
            color: (typeof p.color === "string" && /^#[0-9a-fA-F]{6}$/.test(p.color)) ? p.color : baseStyle[k].color,
            opacity: (typeof p.opacity === "number" && p.opacity >= 0 && p.opacity <= 1) ? p.opacity : baseStyle[k].opacity,
          };
          labels[k] = !!p.labeled;
        });
        let order = Array.isArray(pf.order) ? pf.order.filter((t) => keys.includes(t)) : keys.slice();
        keys.forEach((k) => { if (!order.includes(k)) order.push(k); });

        if (cancelled) return;
        setLayerOrder(order);
        setLayerVisibility(vis);
        setLayerStyle(style);
        setLabelLayers(labels);
        setExportLayers(Object.fromEntries(keys.map((k) => [k, true])));
        setServerStats(Object.fromEntries(keys.map((k) => [k, null])));
        if (typeof pf.basemap === "string" && BASEMAPS[pf.basemap]) setBasemap(pf.basemap);
        if (typeof pf.legendExpanded === "boolean") {
          setLegendExpanded(pf.legendExpanded);
          try { localStorage.setItem("mapLegendExpanded", pf.legendExpanded ? "1" : "0"); } catch (e) { /* ignore */ }
        }
        if (keys.length) {
          setActiveTable(keys[0]);
          setLocationLayer(keys[0]);
          setQueryLayer(keys[0]);
        }
        setPrefsLoaded(true);
        setConfigLoaded(true);
      } catch (err) {
        console.error("Failed to load map layers", err);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist any preference change back to the server for this user.
  useEffect(() => {
    if (!prefsLoaded) return;
    const layers = {};
    layersCfg.forEach((l) => {
      const t = l.table;
      layers[t] = {
        color: (layerStyle[t] && layerStyle[t].color) || undefined,
        opacity: (layerStyle[t] && layerStyle[t].opacity) ?? undefined,
        visible: !!layerVisibility[t],
        labeled: !!labelLayers[t],
      };
    });
    const t = setTimeout(() => {
      axios.put("/api/v1/prefs", { data: { basemap, order: layerOrder, layers, legendExpanded } }, { headers: authHeaders() })
        .catch((err) => console.error("Failed to save preferences", err));
    }, 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap, layerOrder, layerStyle, layerVisibility, labelLayers, legendExpanded, prefsLoaded]);

  useEffect(() => {
    if (!configLoaded || !layersCfg.length) return;
    loadStats().then((stats) => fitStatsOnce(stats));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configLoaded]);
  useEffect(() => {
    if (!configLoaded) return;
    loadStats(selection ? selection.id : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection && selection.id]);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedFilter(tableFilter), 400);
    return () => clearTimeout(t);
  }, [tableFilter]);
  useEffect(() => {
    setTablePage(0);
  }, [activeTable, debouncedFilter, selection && selection.id]);
  useEffect(() => {
    if (activeTable) fetchTable(tablePage, debouncedFilter, selection ? selection.id : null, activeTable);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTable, debouncedFilter, tablePage, selection && selection.id]);
  useEffect(() => {
    if (!queryLayer || layerCols[queryLayer]) return;
    axios.get(`/api/v1/layers/${apiLayer(queryLayer)}/rows`, {
      headers: authHeaders(),
      params: { limit: 1 },
    }).then((res) => {
      setLayerCols((prev) => ({ ...prev, [queryLayer]: normCols(res.data.columns) }));
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryLayer]);
  const handleSearch = async (e) => {
    e.preventDefault();
    if (!searchQuery) return;

    const coordMatch = searchQuery.match(/^(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)$/);
    if (coordMatch) {
      const lat = parseFloat(coordMatch[1]);
      const lng = parseFloat(coordMatch[3]);
      if (mapRef.current) {
        mapRef.current.flyTo({ center: [lng, lat], zoom: 19 });
      }
      return;
    }

    const keys = layersCfg.map((l) => l.table);
    if (!keys.length) return;
    try {
      const token = localStorage.getItem("token");
      const headers = { Authorization: "Bearer " + token };
      const resArr = await Promise.all(keys.map((k) =>
        axios.get(`/api/v1/layers/${apiLayer(k)}/search?q=` + searchQuery, { headers })));
      const matches = resArr.flatMap((res, i) =>
        (res.data.features || []).map((f) => ({ layer: keys[i], feature: f })));
      setSearchMatches(matches);
      setSearchResults({ type: "FeatureCollection", features: matches.map((m) => m.feature) });
      if (matches.length > 0) {
        zoomToFeature(matches[0].feature, 16);
      }
    } catch (err) {
      console.error("Search failed", err);
    }
  };
  const clearSearch = () => {
    setSearchQuery("");
    setSearchMatches([]);
    setSearchResults(null);
    setSelectedFeature(null);
  };

  const handleTopologyCheck = async () => {
    try {
      setTopologyResults(null);
      const token = localStorage.getItem("token");
      const headers = { Authorization: "Bearer " + token };
      const res = await axios.get(`/api/v1/analysis/topology/${TOPOLOGY_TABLE}`, { headers });
      setTopologyResults(res.data.overlaps);
    } catch (err) {
      console.error("Topology check failed", err);
    }
  };

  const onUpdateDraw = useCallback((e) => {
    if (e.features && e.features.length > 0) {
      const geometry = e.features[0].geometry;
      setDrawnGeom(geometry);
      if (activeTool === 'measure') {
        setMeasureResult(measureGeom(geometry));
        setMeasureSegs(geometry.type === 'LineString'
          ? segmentsWithMidpoints(geometry.coordinates)
          : ringSegments(geometry.coordinates && geometry.coordinates[0]));
      }
    }
  }, [activeTool]);

  const segSigRef = useRef(null);
  const onDrawRender = useCallback(() => {
    if (activeTool !== 'measure' || !drawInstance) return;
    try {
      const all = drawInstance.getAll();
      const feat = (all.features || []).find((f) => f.geometry && (f.geometry.type === 'LineString' || f.geometry.type === 'Polygon'));
      const g = feat && feat.geometry;
      if (!g) {
        if (segSigRef.current !== null) { segSigRef.current = null; setMeasureSegs([]); }
        return;
      }
      if (g.type === 'LineString') {
        if (measureMode !== 'length') { if (segSigRef.current !== null) { segSigRef.current = null; setMeasureSegs([]); } return; }
        const coords = g.coordinates;
        if (!coords || coords.length < 2) { if (segSigRef.current !== null) { segSigRef.current = null; setMeasureSegs([]); } return; }
        const sig = 'L' + coords.map((p) => p[0].toFixed(6) + ',' + p[1].toFixed(6)).join('|');
        if (segSigRef.current === sig) return;
        segSigRef.current = sig;
        setMeasureSegs(segmentsWithMidpoints(coords));
        setDrawnGeom(g);
        return;
      }
      // Polygon
      if (measureMode !== 'area') { if (segSigRef.current !== null) { segSigRef.current = null; setMeasureSegs([]); } return; }
      const ring = g.coordinates && g.coordinates[0];
      if (!ring || ring.length < 3) { if (segSigRef.current !== null) { segSigRef.current = null; setMeasureSegs([]); } return; }
      const psig = 'P' + ring.map((p) => p[0].toFixed(6) + ',' + p[1].toFixed(6)).join('|');
      if (segSigRef.current === psig) return;
      segSigRef.current = psig;
      setMeasureSegs(ringSegments(ring));
      setMeasureResult(measureGeom(g));
      setDrawnGeom(g);
    } catch { /* none */ }
  }, [activeTool, measureMode, drawInstance]);

  const onDrawDelete = useCallback(() => {
    if (drawInstance) {
      const all = drawInstance.getAll();
      if (all.features.length === 0) {
        setDrawnGeom(null);
        setMeasureResult(null);
        setMeasureSegs([]);
        deleteSelection();
      }
    }
  }, [drawInstance]);

  const runLocationSearch = async () => {
    if (!drawnGeom || drawnGeom.type !== "Polygon" || !locationLayer) return;
    try {
      const res = await axios.post(`/api/v1/analysis/intersect/${apiLayer(locationLayer)}`, { geometry: drawnGeom }, { headers: authHeaders() });
      const feats = res.data.features || [];
      const reqs = [...new Set(feats.map((f) => (f.properties || {}).Req_Number).filter(Boolean))];
      let sid = null;
      if (reqs.length > 0) {
        const sres = await axios.post("/api/v1/layers/selections", { reqs }, { headers: authHeaders() });
        sid = sres.data.selection_id;
      }
      const flatBBox = (geometry) => {
        let minx = 180, miny = 90, maxx = -180, maxy = -90;
        const eat = (x, y) => { if (Number.isFinite(x) && Number.isFinite(y)) { if (x < minx) minx = x; if (y < miny) miny = y; if (x > maxx) maxx = x; if (y > maxy) maxy = y; } };
        const walk = (c) => { if (!c) return; if (typeof c[0] === "number") eat(c[0], c[1]); else c.forEach(walk); };
        walk(geometry && geometry.coordinates);
        return minx <= maxx ? [minx, miny, maxx, maxy] : null;
      };
      const sample = feats.map((f) => ({ ...(f.properties || {}), bbox: flatBBox(f.geometry) }));
      setSelection({ id: sid, layer: locationLayer, count: feats.length, bbox: null, sample: sample.slice(0, 200) });
      if (feats.length > 0) flyToGeojson({ type: "FeatureCollection", features: feats });
    } catch (err) {
      console.error("Location search failed", err);
    }
  };
  const clearLocation = () => {
    if (drawInstance) {
      try { drawInstance.trash(); } catch (e) { /* no drawing to remove */ }
    }
    setDrawnGeom(null);
    deleteSelection();
    setOverlapPairs(null);
    setOverlapInvalid(null);
    setOverlapErr("");
  };

  /* Same-layer overlap / self-intersection check (no drawn polygon needed). */
  const runOverlapCheck = async () => {
    if (!locationLayer || overlapBusy) return;
    setOverlapBusy(true);
    setOverlapErr("");
    try {
      const res = await axios.post(
        "/api/v1/analysis/same-layer-overlaps",
        { layer: locationLayer, min_overlap_sqm: 1.0 },
        { headers: authHeaders() }
      );
      setOverlapPairs(res.data.overlaps || []);
      setOverlapInvalid(res.data.invalid || []);
    } catch (err) {
      setOverlapPairs(null);
      setOverlapInvalid(null);
      setOverlapErr(
        (err && err.response && err.response.data && err.response.data.detail) ||
        (err && err.message) || "Overlap check failed"
      );
    } finally {
      setOverlapBusy(false);
    }
  };

  const zoomToOverlap = (p) => {
    const b = geomBounds(p && p.geom);
    const m = mapRef.current;
    if (b && m) m.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 90, maxZoom: 19, duration: 1000 });
  };

  const recLabel = (rec) => {
    const pr = (rec && rec.props) || {};
    const r = pr.Req_Number || pr.req_number;
    return r ? String(r) : (rec && rec.id) ? "#" + rec.id : "?";
  };
  const recOwner = (rec) => {
    const pr = (rec && rec.props) || {};
    return pr.Owner_Name || pr.owner_name || "";
  };
  const fmtArea = (sqm) => {
    const v = Number(sqm) || 0;
    return (Math.round(v * 10) / 10).toLocaleString("en-US", { maximumFractionDigits: 1 }) + " m²";
  };
  const fetchTable = async (page, filt, selId, table) => {
    if (!table) return;
    try {
      const res = await axios.get(`/api/v1/layers/${apiLayer(table)}/rows`, {
        headers: authHeaders(),
        params: { limit: TABLE_PAGE_SIZE, offset: page * TABLE_PAGE_SIZE, q: filt || "", ...(selId ? { sel: selId } : {}) },
      });
      setTableRows({ items: res.data.items || [], total: res.data.total || 0, columns: normCols(res.data.columns) });
      setLayerCols((prev) => ({ ...prev, [table]: normCols(res.data.columns) }));
    } catch (err) {
      console.error("Table load failed", err);
    }
  };
  const startDrawing = () => {
    if (drawInstance) {
      try { drawInstance.deleteAll(); } catch (e) { /* none */ }
      drawInstance.changeMode('draw_polygon');
    }
  };
  const startMeasure = (mode) => {
    setActiveTool('measure');
    setMeasureMode(mode);
    setMeasureUnit("auto");
    setMeasureSegs([]);
    if (drawInstance) {
      try { drawInstance.deleteAll(); } catch (e) { /* none */ }
      drawInstance.changeMode(mode === 'area' ? 'draw_polygon' : 'draw_line_string');
    }
  };

  // Leaving an interactive drawing tool cancels any in-progress vertex input so
  // stray clicks cannot leak into other tools (e.g. while printing/exporting).
  useEffect(() => {
    if (!drawInstance || typeof drawInstance.getMode !== 'function') return;
    if (activeTool !== 'measure' && activeTool !== 'location') {
      const m = drawInstance.getMode();
      if (m === 'draw_line_string' || m === 'draw_polygon') {
        try { drawInstance.changeMode('simple_select'); } catch (e) { /* none */ }
      }
    }
  }, [activeTool, drawInstance]);

  const onClick = (event) => {
    if (activeTool === 'polyselect' || activeTool === 'print') return;
    const feature = event.features && event.features[0];
    if (feature) {
      setSelectedFeature({
        longitude: event.lngLat.lng,
        latitude: event.lngLat.lat,
        properties: feature.properties,
        layer: feature.layer && feature.layer.id
      });
    }
  };

  const layerInfo = (layerId) => {
    const id = layerId || "";
    if (id.startsWith("search")) return { label: "Search Result", color: "#f1c40f" };
    if (id.startsWith("aoi")) return { label: "Area Result", color: "#9b59b6" };
    if (id.startsWith("query")) return { label: "Selection", color: "#06b6d4" };
    if (id.startsWith("upl")) return { label: "Upload Preview", color: "#f39c12" };
    const t = id.replace(/-(fill|casing|line|circle|label)$/, "");
    const cfg = layerByTable(t);
    if (cfg) return { label: cfg.label, color: cfg.color };
    return { label: "Feature Details", color: "#6b7280" };
  };

  const scaleText = () => {
    const lat = cursor ? cursor.lat : 27;
    const mpp = (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, mapZoom);
    const scale = "1:" + Math.round(mpp * 3780).toLocaleString();
    return cursor
      ? `Lng ${cursor.lng.toFixed(5)}  |  Lat ${cursor.lat.toFixed(5)}  |  Scale ${scale}`
      : `Move over the map  |  Scale ${scale}`;
  };

  const downloadFile = (filename, content, mime) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };
  const serverExport = async (fmt) => {
    setExporting(fmt);
    setExportError(null);
    try {
      const layers = layersCfg.map((l) => l.table).filter((k) => exportLayers[k]);
      const payload = selection ? { layers, format: fmt, sel: selection.id } : { layers, format: fmt };
      const token = localStorage.getItem("token");
      const res = await axios.post("/api/v1/export/run", payload, {
        headers: { Authorization: "Bearer " + token },
        responseType: "blob",
      });
      let filename = `export_${fmt}.zip`;
      const disp = res.headers && res.headers["content-disposition"];
      if (disp) {
        const m = disp.match(/filename="?([^";]+)"?/);
        if (m) filename = m[1];
      }
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      let msg = "Export failed";
      try {
        const txt = await err.response?.data?.text();
        if (txt) {
          const j = JSON.parse(txt);
          if (j.detail) msg = typeof j.detail === "string" ? j.detail : "Export failed";
        }
      } catch (e) { /* keep generic message */ }
      setExportError(msg);
    } finally {
      setExporting(null);
    }
  };
  const flyToGeojson = (geojson) => {
    if (!geojson || !geojson.features || !geojson.features.length || !mapRef.current) return;
    let minx = 180, miny = 90, maxx = -180, maxy = -90;
    const eat = (x, y) => {
      if (Number.isFinite(x) && Number.isFinite(y)) {
        if (x < minx) minx = x;
        if (y < miny) miny = y;
        if (x > maxx) maxx = x;
        if (y > maxy) maxy = y;
      }
    };
    const walk = (c) => {
      if (!c) return;
      if (typeof c[0] === "number") eat(c[0], c[1]);
      else c.forEach(walk);
    };
    geojson.features.forEach((f) => { if (f.geometry) walk(f.geometry.coordinates); });
    if (minx > maxx || minx < -180 || maxx > 180 || miny < -90 || maxy > 90) return;
    try {
      mapRef.current.fitBounds([[minx, miny], [maxx, maxy]], { padding: 60, duration: 1200 });
    } catch (e) { /* map not ready */ }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploadFileName(file.name);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("layer_name", "land");

    try {
        setUploadStatus("Uploading & processing...");
        const token = localStorage.getItem("token");
        const res = await axios.post("/api/v1/upload/process", formData, {
            headers: { 
                "Content-Type": "multipart/form-data",
                Authorization: "Bearer " + token 
            }
        });
        setUploadPreview(res.data.geojson);
        flyToGeojson(res.data.geojson);
        setUploadStatus("Viewing " + res.data.count + " features (not saved to database).");
    } catch (err) {
        console.error(err);
        setUploadPreview(null);
        setUploadStatus("Error: " + (err.response?.data?.detail || 'Upload failed'));
    }
  };

  const getStatusClass = (status) => {
    if (!status) return "";
    if (status.startsWith("Error")) return "bg-red-100 text-red-700";
    if (status.startsWith("Success")) return "bg-green-100 text-green-700";
    return "bg-blue-100 text-blue-700";
  };

  const interactiveLayerIds = layersCfg.flatMap((cfg) =>
    isPointLike(cfg.gtype) ? [`${cfg.table}-circle`]
      : isLineLike(cfg.gtype) ? [`${cfg.table}-line`]
      : [`${cfg.table}-fill`]
  );
  const displayCols = (tableRows.columns && tableRows.columns.length ? tableRows.columns.slice(0, 4).map((c) => (typeof c === "string" ? c : c.name)) : ["Req_Number", "Owner_Name", "Area_SQM"]);
  const colLabel = (c) => (c === "Req_Number" ? "Request" : c === "Owner_Name" ? "Owner" : c === "Area_SQM" ? "Area m²" : c);

  // Union of loaded layer extents - used by the Print Layout locator inset.
  const fullExtent = useMemo(() => {
    const bbs = layersCfg.map((l) => serverStats[l.table] && serverStats[l.table].bbox).filter(Boolean);
    return bbs.length ? unionBB(bbs) : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layersCfg, serverStats]);

  return (
    <div className="flex-1 relative overflow-hidden">
      
      {/* Floating Search Bar */}
      <div className="absolute top-4 left-4 z-30" style={{ width: pw('search') }}>
        <form onSubmit={handleSearch} className="relative flex items-center bg-white rounded-full shadow-lg overflow-hidden border border-gray-200">
          <div className="pl-4 text-gray-500">
            <Search className="w-5 h-5" />
          </div>
          <input 
            type="text" 
            placeholder="Search Req No, Owner, or Lat,Long..." 
            className="w-full px-4 py-3 text-sm focus:outline-none"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          <button type="submit" className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 text-sm font-medium transition-colors">
            Search
          </button>
          <ResizeHandle anchor="left" width={pw('search')} min={300} max={620} onWidth={(w) => setPanelWidth('search', w)} />
        </form>
        {searchMatches.length > 0 && (
          <div className="mt-2 bg-white rounded-lg shadow-lg border border-gray-200 overflow-hidden">
            <div className="flex justify-between items-center px-3 py-2 bg-gray-50 border-b border-gray-100">
              <span className="text-xs font-bold text-gray-500">{searchMatches.length} result{searchMatches.length > 1 ? "s" : ""}</span>
              <button onClick={clearSearch} className="text-gray-400 hover:text-gray-700">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="max-h-64 overflow-y-auto">
              {searchMatches.slice(0, 100).map((m, i) => (
                <button
                  key={i}
                  onClick={() => zoomToFeature(m.feature, 16)}
                  className="w-full text-left px-3 py-2 hover:bg-blue-50 flex items-center gap-2 border-b border-gray-50"
                >
                  <span className="text-[10px] font-bold uppercase rounded px-1.5 py-0.5 flex-shrink-0 text-white" style={{ backgroundColor: layerColor(m.layer) }}>
                    {layerLabel(m.layer).slice(0, 4)}
                  </span>
                  <span className="text-xs text-gray-800 truncate">
                    {m.feature.properties.Req_Number || "N/A"} — {m.feature.properties.Owner_Name || ""}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      
      
      {/* Layers Panel */}
      {activeTool === 'layers' && (
        <div className="absolute top-[100px] left-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200" style={{ width: pw('layers') }}>
          <ResizeHandle anchor="left" width={pw('layers')} min={230} max={520} onWidth={(w) => setPanelWidth('layers', w)} />
          <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Layers</h3>
            <div className="flex items-center gap-1">
              <button onClick={() => setLayerVisibility({ ...allOn })} className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 px-1">All</button>
              <button onClick={() => setLayerVisibility({ ...allOff })} className="text-[11px] font-semibold text-gray-500 hover:text-gray-700 px-1">None</button>
              <button onClick={() => setActiveTool(null)} className="text-gray-400 hover:text-gray-700 ml-1">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
          <div className="p-3 space-y-3">
            {orderedMeta.map((m) => {
              const st = layerStats(m.table);
              return (
                <div
                  key={m.table}
                  draggable
                  onDragStart={() => setDragKey(m.table)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => dropOnLayer(m.table)}
                  onDragEnd={() => setDragKey(null)}
                  className={"border border-gray-100 rounded-lg p-2.5 bg-gray-50/50 " + (dragKey === m.table ? "opacity-50" : "")}
                >
                  <div className="flex items-center gap-1.5">
                    <span title="Drag to reorder" className="cursor-grab active:cursor-grabbing text-gray-300 hover:text-gray-500 flex-shrink-0">
                      <GripVertical className="w-4 h-4" />
                    </span>
                    <input type="checkbox" checked={layerVisibility[m.table]} onChange={(e) => setLayerVisibility({ ...layerVisibility, [m.table]: e.target.checked })} className="rounded border-gray-300 text-green-600 focus:ring-green-500" />
                    <label className="w-5 h-5 rounded-full cursor-pointer border border-gray-300 shadow-sm flex-shrink-0" style={{ backgroundColor: layerStyle[m.table].color }} title="Layer color">
                      <input type="color" value={layerStyle[m.table].color} onChange={(e) => setLayerStyle({ ...layerStyle, [m.table]: { ...layerStyle[m.table], color: e.target.value } })} className="sr-only" />
                    </label>
                    <span className="text-sm font-medium text-gray-800 flex-1">{m.label}</span>
                    <span className="text-[11px] font-bold text-gray-500 bg-white border border-gray-200 rounded-full px-2 py-0.5">{st.count}</span>
                    <span className="flex flex-col flex-shrink-0 leading-none">
                      <button onClick={() => moveLayer(m.table, -1)} title="Move up" className="p-0.5 rounded text-gray-400 hover:bg-gray-200 hover:text-gray-700">
                        <ChevronUp className="w-3.5 h-3.5" />
                      </button>
                      <button onClick={() => moveLayer(m.table, 1)} title="Move down" className="p-0.5 rounded text-gray-400 hover:bg-gray-200 hover:text-gray-700">
                        <ChevronDown className="w-3.5 h-3.5" />
                      </button>
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-2">
                    <span className="text-[10px] text-gray-400 w-12 flex-shrink-0">Opacity</span>
                    <input type="range" min="5" max="100" value={Math.round(layerStyle[m.table].opacity * 100)} onChange={(e) => setLayerStyle({ ...layerStyle, [m.table]: { ...layerStyle[m.table], opacity: e.target.value / 100 } })} className="flex-1 h-1 accent-green-600 min-w-0" />
                    <span className="text-[10px] text-gray-500 w-8 text-right flex-shrink-0">{Math.round(layerStyle[m.table].opacity * 100)}%</span>
                    <button onClick={() => zoomToLayer(m.table)} title={"Zoom to " + m.label} className="p-1 rounded text-blue-600 hover:bg-blue-50 flex-shrink-0">
                      <ZoomIn className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => { setActiveTable(m.table); setTableLocked(m.table); setActiveTool('table'); }} title={"Open attribute table for " + m.label} className="p-1 rounded text-emerald-600 hover:bg-emerald-50 flex-shrink-0">
                      <Table className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => setLabelLayers({ ...labelLayers, [m.table]: !labelLayers[m.table] })} title={"Toggle labels for " + m.label} className={"p-1 rounded flex-shrink-0 " + (labelLayers[m.table] ? "text-purple-700 bg-purple-100" : "text-gray-400 hover:bg-gray-100")}>
                      <Type className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <p className="text-[11px] text-gray-500 mt-1">{st.areaText}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Export Data Panel */}
      {activeTool === 'export' && (
        <div className="absolute top-[100px] left-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200" style={{ width: pw('export') }}>
          <ResizeHandle anchor="left" width={pw('export')} min={230} max={520} onWidth={(w) => setPanelWidth('export', w)} />
          <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Export Data</h3>
            <button onClick={() => setActiveTool(null)} className="text-gray-400 hover:text-gray-700">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="p-3 space-y-3">
            <div>
              <p className="text-[11px] font-semibold text-gray-500 mb-1">Layers</p>
              {layersCfg.map((l) => {
                const k = l.table;
                const n = ((serverStats[k] && serverStats[k].count) || 0);
                return (
                  <label key={k} className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer py-0.5">
                    <input
                      type="checkbox"
                      checked={!!exportLayers[k]}
                      onChange={(e) => setExportLayers({ ...exportLayers, [k]: e.target.checked })}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="flex-1">{l.label}</span>
                    <span className="text-[11px] font-bold text-gray-500">{n}</span>
                  </label>
                );
              })}
            </div>
            <div>
              <p className="text-[11px] font-semibold text-gray-500 mb-1">Format</p>
              <div className="grid grid-cols-3 gap-1">
                {[["geojson", "GeoJSON"], ["csv", "CSV"], ["shp", "Shapefile"], ["gpkg", "GPKG"], ["filegdb", "GeoDB"]].map(([v, label]) => (
                  <button key={v} onClick={() => setExportFormat(v)} className={"px-2 py-1.5 rounded text-xs font-semibold transition " + (exportFormat === v ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200")}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {selection && (
              <p className="text-[11px] text-cyan-700 bg-cyan-50 border border-cyan-100 rounded px-2 py-1">Filtered view will be exported.</p>
            )}
            <button onClick={() => serverExport(exportFormat)} disabled={exporting != null} className="w-full px-3 py-2 rounded-md text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 inline-flex items-center justify-center">
              <Download className="w-3.5 h-3.5 mr-1.5" /> {exporting ? "Exporting..." : "Export"}
            </button>
            {exportError && (
              <p className="text-[11px] text-red-600 break-words">{exportError}</p>
            )}
          </div>
        </div>
      )}

      {/* Select by Location Panel */}
      {activeTool === 'location' && (
        <div className="absolute top-[100px] left-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200" style={{ width: pw('location') }}>
          <ResizeHandle anchor="left" width={pw('location')} min={230} max={520} onWidth={(w) => setPanelWidth('location', w)} />
          <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Select by Location</h3>
            <button onClick={() => setActiveTool(null)} className="text-gray-400 hover:text-gray-700">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="p-3 space-y-2">
            <div>
              <p className="text-[11px] font-semibold text-gray-500 mb-1">Layer</p>
              <select
                value={locationLayer || ""}
                onChange={(e) => {
                  setLocationLayer(e.target.value);
                  setOverlapPairs(null);
                  setOverlapInvalid(null);
                  setOverlapErr("");
                }}
                className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-orange-500"
              >
                {layersCfg.map((l) => (
                  <option key={l.table} value={l.table}>{l.label}</option>
                ))}
              </select>
            </div>
            <button
              onClick={startDrawing}
              disabled={!drawInstance}
              className="w-full px-3 py-2 rounded-md text-xs font-semibold bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-50"
            >
              Draw area on map
            </button>
            <p className="text-[11px] text-gray-500">
              {drawnGeom ? (drawnGeom.type === "Polygon" ? "Area drawn — ready to search." : "Shape is not a polygon — draw a polygon first.") : "Draw a polygon on the map first."}
            </p>
            <div className="flex gap-2">
              <button onClick={runLocationSearch} disabled={!(drawnGeom && drawnGeom.type === "Polygon")} className="flex-1 px-3 py-2 rounded-md text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                Find intersecting
              </button>
              <button onClick={clearLocation} className="px-3 py-2 rounded-md text-xs font-semibold bg-white text-gray-600 border border-gray-300 hover:bg-gray-100">
                Clear
              </button>
            </div>
            <div className="border-t border-gray-100 pt-2 mt-1">
              <p className="text-[11px] font-semibold text-gray-500 mb-1.5">Same-layer check (no polygon needed)</p>
              <button
                onClick={runOverlapCheck}
                disabled={!locationLayer || overlapBusy}
                className="w-full px-3 py-2 rounded-md text-xs font-semibold bg-rose-500 text-white hover:bg-rose-600 disabled:opacity-50 inline-flex items-center justify-center gap-1.5"
              >
                {overlapBusy ? "Scanning…" : <><DatabaseZap className="w-3.5 h-3.5" /> Find self-intersecting / overlapping — same layer</>}
              </button>
              {overlapErr && <p className="text-[11px] text-red-600 mt-1.5">{overlapErr}</p>}
              {overlapPairs !== null && (
                <div className="mt-2 space-y-2">
                  {overlapPairs.length === 0 && overlapInvalid.length === 0 ? (
                    <p className="text-[11px] text-gray-500">No overlapping or invalid features found in «{layersCfg.find((l) => l.table === locationLayer)?.label || locationLayer}».</p>
                  ) : (
                    <>
                      {overlapPairs.length > 0 && (
                        <div>
                          <p className="text-[11px] font-bold text-rose-600 mb-1">{overlapPairs.length} overlapping pair(s) — click to zoom</p>
                          <div className="max-h-44 overflow-y-auto border border-gray-200 rounded-md divide-y divide-gray-100">
                            {overlapPairs.map((p, i) => (
                              <button key={i} onClick={() => zoomToOverlap(p)} className="w-full text-left px-2 py-1.5 hover:bg-rose-50 text-xs text-gray-800">
                                <span className="font-semibold">{recLabel(p.feature1)}</span> ↔ <span className="font-semibold">{recLabel(p.feature2)}</span>
                                <span className="text-gray-500"> · {fmtArea(p.overlap_area_sqm)}</span>
                                <span className="block text-[10px] text-gray-400 truncate">{recOwner(p.feature1)}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                      {overlapInvalid.length > 0 && (
                        <div>
                          <p className="text-[11px] font-bold text-amber-600 mb-1">{overlapInvalid.length} invalid / self-intersecting feature(s) — click to zoom</p>
                          <div className="max-h-32 overflow-y-auto border border-gray-200 rounded-md divide-y divide-gray-100">
                            {overlapInvalid.map((iv, i) => (
                              <button key={i} onClick={() => zoomToOverlap(iv)} className="w-full text-left px-2 py-1.5 hover:bg-amber-50 text-xs text-gray-800">
                                <span className="font-semibold">{iv.id}</span> — <span className="text-amber-700">{iv.reason}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
            {selection && selection.layer === locationLayer && (
              <div>
                <p className="text-[11px] font-bold text-gray-500 mb-1">{selection.count} intersecting — click to zoom</p>
                <div className="max-h-48 overflow-y-auto border border-gray-200 rounded-md divide-y divide-gray-100">
                  {(selection.sample || []).map((it, i) => (
                    <button key={i} onClick={() => zoomToItem(it)} className="w-full text-left px-2 py-1.5 hover:bg-orange-50 text-xs text-gray-800 truncate">
                      {it.Req_Number || "-"} — {it.Owner_Name || ""}
                    </button>
                  ))}
                </div>
                {selection.count > (selection.sample || []).length && (
                  <p className="text-[11px] text-gray-400 mt-1">Showing first {(selection.sample || []).length} of {selection.count}.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Select by Attributes Panel */}
      {activeTool === 'query' && (
        <div className="absolute top-[100px] left-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200" style={{ width: pw('query') }}>
          <ResizeHandle anchor="left" width={pw('query')} min={230} max={520} onWidth={(w) => setPanelWidth('query', w)} />
          <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Select by Attributes</h3>
            <button onClick={() => setActiveTool(null)} className="text-gray-400 hover:text-gray-700">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="p-3 space-y-2">
            <div>
              <p className="text-[11px] font-semibold text-gray-500 mb-1">Layer</p>
              <select
                value={queryLayer || ""}
                onChange={(e) => setQueryLayer(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-purple-500"
              >
                {layersCfg.map((l) => (
                  <option key={l.table} value={l.table}>{l.label}</option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <p className="text-[11px] font-semibold text-gray-500 mb-1">Field</p>
                <select
                  value={queryField}
                  onChange={(e) => { setQueryField(e.target.value); setQueryOp(QUERY_OPS[fieldTypeOf(e.target.value)][0][0]); }}
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-purple-500"
                >
                  {queryFields.map((f) => (
                    <option key={f.key} value={f.key}>{f.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <p className="text-[11px] font-semibold text-gray-500 mb-1">Operator</p>
                <select
                  value={queryOp}
                  onChange={(e) => setQueryOp(e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-purple-500"
                >
                  {QUERY_OPS[fieldTypeOf(queryField)].map(([v, label]) => (
                    <option key={v} value={v}>{label}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex gap-2">
              <input
                type={fieldTypeOf(queryField) === "date" ? "date" : fieldTypeOf(queryField) === "number" ? "number" : "text"}
                value={queryValue}
                onChange={(e) => setQueryValue(e.target.value)}
                placeholder="Value..."
                className="flex-1 border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-purple-500"
              />
              <button
                onClick={() => {
                  if (!queryValue.toString().trim()) return;
                  setQueryConds([...queryConds, { field: queryField, op: queryOp, type: fieldTypeOf(queryField), value: queryValue }]);
                  setQueryValue("");
                }}
                className="px-3 py-1.5 rounded-md text-xs font-semibold bg-purple-600 text-white hover:bg-purple-700"
              >
                Add
              </button>
            </div>
            {queryConds.length > 0 && (
              <div className="space-y-1">
                {queryConds.map((c, i) => (
                  <div key={i} className="flex items-center gap-2 bg-purple-50 border border-purple-100 rounded px-2 py-1 text-xs">
                    <span className="text-gray-700 flex-1 truncate">{c.field} {c.op} {c.value}{i < queryConds.length - 1 ? "  AND" : ""}</span>
                    <button onClick={() => setQueryConds(queryConds.filter((_, j) => j !== i))} className="text-gray-400 hover:text-red-600">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={applyQuery} disabled={queryConds.length === 0} className="flex-1 px-3 py-2 rounded-md text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                Apply selection
              </button>
              <button onClick={clearQuery} className="px-3 py-2 rounded-md text-xs font-semibold bg-white text-gray-600 border border-gray-300 hover:bg-gray-100">
                Clear
              </button>
            </div>
            {selection && selection.layer === queryLayer && (
              <div>
                <p className="text-[11px] font-bold text-gray-500 mb-1">{selection.count} selected — click to zoom</p>
                <div className="max-h-48 overflow-y-auto border border-gray-200 rounded-md divide-y divide-gray-100">
                  {(selection.sample || []).map((it, i) => (
                    <button key={i} onClick={() => zoomToItem(it)} className="w-full text-left px-2 py-1.5 hover:bg-purple-50 text-xs text-gray-800 truncate">
                      {it.Req_Number || "-"} — {it.Owner_Name || ""}
                    </button>
                  ))}
                </div>
                {selection.count > (selection.sample || []).length && (
                  <p className="text-[11px] text-gray-400 mt-1">Showing first {(selection.sample || []).length} of {selection.count}.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Basemap Mini Popup */}
      {activeTool === 'basemap' && (
        <div className="absolute top-[150px] right-[50px] z-20 bg-white rounded shadow-lg border border-gray-200 p-2" style={{ width: pw('basemap') }}>
          <ResizeHandle anchor="right" width={pw('basemap')} min={180} max={420} onWidth={(w) => setPanelWidth('basemap', w)} />
          <div className="flex justify-between items-center mb-2 px-1">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Basemap</h3>
            <button onClick={() => setActiveTool(null)} className="text-gray-400 hover:text-gray-700">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="space-y-1">
            <button onClick={() => { setBasemap("carto"); setActiveTool(null); }} className={"w-full text-left px-3 py-2 rounded text-sm transition " + (basemap === "carto" ? "bg-indigo-50 text-indigo-700 font-medium" : "text-gray-700 hover:bg-gray-100")}>Carto Positron</button>
            <button onClick={() => { setBasemap("osm"); setActiveTool(null); }} className={"w-full text-left px-3 py-2 rounded text-sm transition " + (basemap === "osm" ? "bg-indigo-50 text-indigo-700 font-medium" : "text-gray-700 hover:bg-gray-100")}>OpenStreetMap</button>
            <button onClick={() => { setBasemap("satellite"); setActiveTool(null); }} className={"w-full text-left px-3 py-2 rounded text-sm transition " + (basemap === "satellite" ? "bg-indigo-50 text-indigo-700 font-medium" : "text-gray-700 hover:bg-gray-100")}>Google Satellite</button>
            <div className="border-t border-gray-100 my-1" />
            <button onClick={() => { setBasemap("none"); setActiveTool(null); }} className={"w-full text-left px-3 py-2 rounded text-sm transition " + (basemap === "none" ? "bg-indigo-50 text-indigo-700 font-medium" : "text-gray-700 hover:bg-gray-100")}>None (no basemap)</button>
          </div>
        </div>
      )}

      {/* Upload Mini Popup */}
      {activeTool === 'upload' && (
        <div className="absolute top-[150px] right-[50px] z-20 bg-white rounded shadow-lg border border-gray-200 p-3" style={{ width: pw('upload') }}>
          <ResizeHandle anchor="right" width={pw('upload')} min={220} max={460} onWidth={(w) => setPanelWidth('upload', w)} />
          <div className="flex justify-between items-center mb-2 px-1">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Upload File</h3>
            <button onClick={() => setActiveTool(null)} className="text-gray-400 hover:text-gray-700">
              <X className="w-4 h-4" />
            </button>
          </div>
          <p className="text-[11px] text-gray-500 mb-2 px-1">Preview a .zip shapefile on the map (not saved).</p>
          <div className="border-2 border-dashed border-blue-300 rounded-lg p-4 text-center hover:bg-blue-50 transition cursor-pointer relative overflow-hidden group mx-1">
            <input
              type="file"
              accept=".zip"
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              onChange={handleFileUpload}
            />
            <UploadCloud className="w-6 h-6 text-blue-400 mx-auto mb-1 group-hover:text-blue-600" />
            <p className="text-xs font-medium text-blue-600">Click or Drop .zip</p>
          </div>
          {uploadFileName && (
            <p className="mt-2 px-1 text-[11px] text-gray-600 truncate">File: <span className="font-mono font-semibold">{uploadFileName}</span></p>
          )}
          {uploadStatus && (
            <div className={"mt-2 mx-1 p-2 text-xs rounded " + getStatusClass(uploadStatus)}>
              {uploadStatus}
            </div>
          )}
          {uploadPreview && (
            <div className="mt-2 flex gap-2 px-1">
              <button onClick={() => flyToGeojson(uploadPreview)} className="flex-1 bg-white border border-blue-300 text-blue-600 hover:bg-blue-50 py-1.5 rounded text-xs font-medium transition">
                Zoom
              </button>
              <button onClick={() => { setUploadPreview(null); setUploadStatus(null); setUploadFileName(null); }} className="flex-1 bg-white border border-red-300 text-red-600 hover:bg-red-50 py-1.5 rounded text-xs font-medium transition">
                Clear
              </button>
            </div>
          )}
        </div>
      )}

      
        {/* Floating Tool Icons (Left Side) */}
        <div className="absolute top-[100px] left-[10px] z-10 flex flex-col gap-2">
            <div className="flex flex-col bg-white rounded shadow-[0_0_0_2px_rgba(0,0,0,0.1)] overflow-hidden">
            <button 
              className={"w-[35px] h-[35px] flex items-center justify-center border-b border-gray-200 " + (activeTool === 'layers' ? 'bg-green-100 text-green-700' : 'text-gray-700 hover:bg-gray-100')}
              onClick={() => setActiveTool(activeTool === 'layers' ? null : 'layers')} title="Layer List"
            >
              <Layers className="w-[18px] h-[18px]" />
            </button>
            <button 
              className={"w-[35px] h-[35px] flex items-center justify-center border-b border-gray-200 " + (activeTool === 'query' ? 'bg-purple-100 text-purple-700' : 'text-gray-700 hover:bg-gray-100')}
              onClick={() => setActiveTool(activeTool === 'query' ? null : 'query')} title="Select by Attributes"
            >
              <Filter className="w-[18px] h-[18px]" />
            </button>
            <button 
              className={"w-[35px] h-[35px] flex items-center justify-center " + (activeTool === 'location' ? 'bg-orange-100 text-orange-700' : 'text-gray-700 hover:bg-gray-100')}
              onClick={() => setActiveTool(activeTool === 'location' ? null : 'location')} title="Select by Location"
            >
              <MapPin className="w-[18px] h-[18px]" />
            </button>
            <button
              className={"w-[35px] h-[35px] flex items-center justify-center " + (activeTool === 'export' ? 'bg-blue-100 text-blue-700' : 'text-gray-700 hover:bg-gray-100')}
              onClick={() => setActiveTool(activeTool === 'export' ? null : 'export')} title="Export Data"
            >
              <Download className="w-[18px] h-[18px]" />
            </button>
            <button
              className={"w-[35px] h-[35px] flex items-center justify-center " + (activeTool === 'polyselect' ? 'bg-violet-100 text-violet-700' : 'text-gray-700 hover:bg-gray-100')}
              onClick={() => setActiveTool(activeTool === 'polyselect' ? null : 'polyselect')} title="Select by Polygon"
            >
              <ScanLine className="w-[18px] h-[18px]" />
            </button>
          </div>
        </div>


      <div className="absolute top-[100px] right-[10px] z-10 flex flex-col gap-2">
       <div className="flex flex-col bg-white rounded shadow-[0_0_0_2px_rgba(0,0,0,0.1)] overflow-hidden mt-2">
          
            <button 
              className={"w-[35px] h-[35px] flex items-center justify-center border-b border-gray-200 " + (activeTool === 'print' ? 'bg-cyan-100 text-cyan-700' : 'text-gray-700 hover:bg-gray-100')}
              onClick={() => setActiveTool(activeTool === 'print' ? null : 'print')} title="Print Layout"
            >
              <Printer className="w-[18px] h-[18px]" />
            </button>

            <button 
              className={"w-[35px] h-[35px] flex items-center justify-center border-b border-gray-200 " + (activeTool === 'basemap' ? 'bg-indigo-100 text-indigo-700' : 'text-gray-700 hover:bg-gray-100')}
              onClick={() => setActiveTool(activeTool === 'basemap' ? null : 'basemap')} title="Change Basemap"
            >
              <MapIcon className="w-[18px] h-[18px]" />
            </button>
            <button 
              className={"w-[35px] h-[35px] flex items-center justify-center " + (activeTool === 'table' ? 'bg-emerald-100 text-emerald-700' : 'text-gray-700 hover:bg-gray-100')}
              onClick={() => { setTableLocked(null); setActiveTool(activeTool === 'table' ? null : 'table'); }} title="Attribute Table"
            >
              <Table className="w-[18px] h-[18px]" />
            </button>
            <button 
            className={"w-[35px] h-[35px] flex items-center justify-center " + (activeTool === 'upload' ? 'bg-blue-100 text-blue-700' : 'text-gray-700 hover:bg-gray-100')}
            onClick={() => setActiveTool(activeTool === 'upload' ? null : 'upload')} title="Upload Shapefile"
          >
            <UploadCloud className="w-[18px] h-[18px]" />
          </button>
            <button
            className={"w-[35px] h-[35px] flex items-center justify-center " + (activeTool === 'measure' ? 'bg-red-100 text-red-700' : 'text-gray-700 hover:bg-gray-100')}
            onClick={() => setActiveTool(activeTool === 'measure' ? null : 'measure')} title="Measure"
          >
            <Ruler className="w-[18px] h-[18px]" />
          </button>
          {isEditor && (
            <button
              className={"w-[35px] h-[35px] flex items-center justify-center border-t border-gray-200 " + (activeTool === 'update' ? 'bg-blue-100 text-blue-700' : 'text-gray-700 hover:bg-gray-100')}
              onClick={() => setActiveTool(activeTool === 'update' ? null : 'update')} title="Update Geometry"
            >
              <DatabaseZap className="w-[18px] h-[18px]" />
            </button>
          )}
        </div>
      </div>

      {/* Measure Floating Panel */}
      {activeTool === 'measure' && (
        <div className="absolute top-[100px] right-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200" style={{ width: pw('measure') }}>
          <ResizeHandle anchor="right" width={pw('measure')} min={230} max={520} onWidth={(w) => setPanelWidth('measure', w)} />
          <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Measure</h3>
            <button onClick={() => setActiveTool(null)} className="text-gray-400 hover:text-gray-700">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="p-3">
            <div className="flex gap-1 mb-2">
              {[["length", "Length"], ["area", "Area"]].map(([v, label]) => (
                <button key={v} onClick={() => startMeasure(v)} className={"flex-1 px-2 py-1.5 rounded text-xs font-semibold transition " + (measureMode === v ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200')}>
                  {label}
                </button>
              ))}
            </div>
            {measureMode === 'length' ? (
              <div className="flex gap-1 mb-2">
                {[["m", "meters"], ["km", "km"]].map(([v, label]) => (
                  <button key={v} onClick={() => setMeasureUnit(v)} className={"px-2 py-1 rounded text-xs font-semibold " + (measureUnit === v ? 'bg-indigo-100 text-indigo-700' : 'text-gray-600 hover:bg-gray-100')}>{label}</button>
                ))}
              </div>
            ) : (
              <div className="flex gap-1 mb-2">
                {[["sqm", "m²"], ["sqkm", "km²"], ["feddan", "feddan"]].map(([v, label]) => (
                  <button key={v} onClick={() => setMeasureUnit(v)} className={"px-2 py-1 rounded text-xs font-semibold " + (measureUnit === v ? 'bg-indigo-100 text-indigo-700' : 'text-gray-600 hover:bg-gray-100')}>{label}</button>
                ))}
              </div>
            )}
            {measureResult ? (
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-center">
                <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1">{measureResult.type === 'length' ? 'Length' : 'Area'}</p>
                <p className="text-lg font-bold text-indigo-700">{(() => {
                  const r = measureResult;
                  if (!r) return '-';
                  if (r.type === 'length') {
                    if (measureUnit === 'km') return (r.meters / 1000).toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' km';
                    if (measureUnit === 'm') return r.meters.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' m';
                    return (r.meters >= 1000 ? (r.meters / 1000).toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' km' : r.meters.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' m');
                  }
                  if (measureUnit === 'sqkm') return (r.sqm / 1000000).toLocaleString('en-US', { maximumFractionDigits: 4 }) + ' km²';
                  if (measureUnit === 'feddan') return (r.sqm / FEDDAN_SQM).toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' feddan';
                  if (measureUnit === 'sqm') return r.sqm.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' m²';
                  if (r.sqm >= 1000000) return (r.sqm / 1000000).toLocaleString('en-US', { maximumFractionDigits: 4 }) + ' km²';
                  if (r.sqm >= 4200.83) return (r.sqm / FEDDAN_SQM).toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' feddan';
                  return r.sqm.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' m²';
                })()}</p>
              </div>
            ) : (
              <p className="text-[11px] text-gray-500 text-center py-2">Choose a mode, then draw on the map.</p>
            )}
            <button onClick={() => { if (drawInstance) { try { drawInstance.deleteAll(); } catch (e) { /* none */ } } setMeasureResult(null); setMeasureSegs([]); }} className="w-full mt-2 px-3 py-1.5 rounded-md text-xs font-semibold bg-white border border-red-300 text-red-600 hover:bg-red-50">
              Clear
            </button>
          </div>
        </div>
      )}

      {/* Select by Polygon Docked Panel */}
      {activeTool === 'polyselect' && (
        <SelectByPolygonPanel
          me={me}
          mapRef={mapApiRef}
          config={{ layers: layersCfg, api_layers: Object.fromEntries(layersCfg.map((l) => [l.table, apiLayer(l.table)])) }}
          onClose={() => setActiveTool(null)}
          panelWidth={pw('polyselect')}
          onPanelWidth={(w) => setPanelWidth('polyselect', w)}
        />
      )}

      {/* Update Geometry Docked Panel */}
      {activeTool === 'update' && isEditor && (
        <UpdateGeometryPanel
          me={me}
          onClose={() => setActiveTool(null)}
          panelWidth={pw('update')}
          onPanelWidth={(w) => setPanelWidth('update', w)}
        />
      )}

      {/* Print Layout Docked Panel */}
      {activeTool === 'print' && (
        <PrintLayoutPanel
          mapRef={mapApiRef}
          basemapStyle={BASEMAPS[basemap]}
          buildDynamic={buildDynamic}
          layersCfg={layersCfg}
          layerOrder={layerOrder}
          layerStyle={layerStyle}
          layerVisibility={layerVisibility}
          fullExtent={fullExtent}
          onClose={() => setActiveTool(null)}
          panelWidth={pw('print')}
          onPanelWidth={(w) => setPanelWidth('print', w)}
        />
      )}

      {/* Attribute Table Floating Panel */}
      {activeTool === 'table' && (
        <div className="absolute top-[100px] right-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200 flex flex-col overflow-hidden max-h-[calc(100vh-185px)]" style={{ width: pw('table') }}>
          <ResizeHandle anchor="right" width={pw('table')} min={340} max={760} onWidth={(w) => setPanelWidth('table', w)} />
          <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100 flex-shrink-0">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
              Attribute Table{tableLocked ? " — " + layerLabel(tableLocked) : ""}
            </h3>
            <button onClick={() => setActiveTool(null)} className="text-gray-400 hover:text-gray-700">
              <X className="w-4 h-4" />
            </button>
          </div>
          {selection && (
            <div className="px-3 py-1.5 bg-cyan-50 border-b border-cyan-100 flex items-center justify-between flex-shrink-0">
              <span className="text-[11px] font-semibold text-cyan-800">Filtered to selection ({tableRows.total} rows)</span>
              <button onClick={async () => { await deleteSelection(); setTablePage(0); if (activeTable) fetchTable(0, debouncedFilter, null, activeTable); }} className="text-[11px] font-semibold text-cyan-700 hover:text-cyan-900">Show all</button>
            </div>
          )}
          <div className="p-3 overflow-y-auto">
            {tableLocked ? (
              <button onClick={() => setTableLocked(null)} className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 mb-2">
                Show all layers
              </button>
            ) : (
            <div className="flex gap-1 mb-3">
              {layersCfg.map((l) => (
                <button key={l.table} onClick={() => setActiveTable(l.table)} className={"flex-1 px-2 py-1.5 rounded text-xs font-semibold transition " + (activeTable === l.table ? "bg-emerald-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200")}>
                  {l.label} ({((serverStats[l.table] && serverStats[l.table].count) || 0)})
                </button>
              ))}
            </div>
            )}
            <input type="text" value={tableFilter} onChange={(e) => setTableFilter(e.target.value)} placeholder="Filter req / owner..." className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-1 focus:ring-emerald-500" />
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <div className="max-h-[50vh] overflow-y-auto">
                <table className="min-w-full divide-y divide-gray-100 text-xs">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      {displayCols.map((c) => (
                        <th key={c} className="px-3 py-2 text-left font-bold text-gray-500 uppercase">{colLabel(c)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                          {tableRows.items.map((it, i) => (
                            <tr key={i} onClick={() => zoomToItem(it)} className="hover:bg-emerald-50 cursor-pointer">
                              {displayCols.map((c) => {
                                let val = it[c];
                                if (c === "Area_SQM" && val !== undefined && val !== null && val !== "-" && Number.isFinite(Number(val))) val = Number(val).toLocaleString();
                                const isNull = val === null || val === undefined || val === "";
                                return (
                                  <td key={c} className={"px-3 py-2 " + (c === "Req_Number" ? "font-medium text-gray-800" : "text-gray-600")}>
                                    {isNull ? "-" : String(val)}
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                          {tableRows.items.length === 0 && (
                            <tr>
                              <td colSpan={displayCols.length} className="px-3 py-6 text-center text-gray-400">No rows.</td>
                            </tr>
                          )}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="flex items-center justify-between mt-2">
              <p className="text-[11px] text-gray-400">Click a row to zoom. {tableRows.total} rows total.</p>
              <div className="flex items-center gap-1">
                <button disabled={tablePage === 0} onClick={() => setTablePage((p) => Math.max(0, p - 1))} className="px-2 py-1 rounded text-[11px] font-semibold bg-white text-gray-600 border border-gray-300 hover:bg-gray-100 disabled:opacity-50">Prev</button>
                <span className="text-[11px] text-gray-500">Page {tablePage + 1}</span>
                <button disabled={(tablePage + 1) * TABLE_PAGE_SIZE >= tableRows.total} onClick={() => setTablePage((p) => p + 1)} className="px-2 py-1 rounded text-[11px] font-semibold bg-white text-gray-600 border border-gray-300 hover:bg-gray-100 disabled:opacity-50">Next</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Slide-out Tool Panel (topology only; all other tools use left mini popups) */}
{(activeTool === 'topology') && (
        <div className="absolute top-0 right-0 h-full bg-white shadow-2xl z-20 border-l border-gray-200 flex flex-col transition-all" style={{ width: pw('topology') }}>
          <ResizeHandle anchor="right" width={pw('topology')} min={280} max={680} onWidth={(w) => setPanelWidth('topology', w)} />
          <div className="flex justify-between items-center p-4 border-b bg-gray-50 flex-shrink-0">
              <h2 className="font-bold text-gray-700 flex items-center">
                {activeTool === 'topology' && <><AlertCircle className="w-5 h-5 mr-2 text-orange-500"/> Topology Check</>}
              </h2>
              <button onClick={() => setActiveTool(null)} className="text-gray-400 hover:text-gray-700 transition">
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-4 overflow-y-auto">
              {activeTool === 'topology' && (
                <div>
                  <p className="text-xs text-gray-500 mb-4">Scan the database for intersecting or overlapping geometries in the land layer.</p>
                  <button onClick={handleTopologyCheck} className="w-full bg-orange-500 text-white py-3 rounded-lg text-sm font-medium hover:bg-orange-600 transition flex justify-center items-center">
                    <AlertCircle className="w-4 h-4 mr-2" /> Run Topology Scan
                  </button>
                  
                  {topologyResults && (
                    <div className="mt-4">
                        <div className={"p-3 rounded-t text-sm font-bold " + (topologyResults.length > 0 ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700")}>
                          {topologyResults.length > 0 ? "Found " + topologyResults.length + " overlaps!" : "No overlaps found! Map is clean."}
                        </div>
                        {topologyResults.length > 0 && (
                          <div className="border border-red-200 border-t-0 rounded-b max-h-64 overflow-y-auto bg-white p-2 text-sm">
                            <ul className="divide-y divide-gray-100">
                              {topologyResults.slice(0, 50).map((r, i) => (
                                <li key={i} className="py-2 px-2 text-gray-700">
                                  ID <strong>{r.id1}</strong> overlaps ID <strong>{r.id2}</strong>
                                </li>
                              ))}
                            </ul>
                            {topologyResults.length > 50 && (
                              <p className="text-xs text-gray-500 text-center mt-2 pt-2 border-t">Showing first 50 results</p>
                            )}
                          </div>
                        )}
                    </div>
                  )}
                </div>
              )}
            </div>
        </div>
      )}

      {/* Cursor coordinates */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 bg-white/95 rounded shadow px-2 py-1 text-xs font-mono text-gray-700 border border-gray-200 whitespace-nowrap flex items-center gap-1 pointer-events-none">
        <span className="px-1">{scaleText()}</span>
        <button onClick={() => { try { mapRef.current.zoomOut(); } catch (e) {} }} title="Zoom out" className="p-1 rounded text-gray-600 hover:bg-gray-200 pointer-events-auto">
          <Minus className="w-3.5 h-3.5" />
        </button>
        <button onClick={() => { try { mapRef.current.zoomIn(); } catch (e) {} }} title="Zoom in" className="p-1 rounded text-gray-600 hover:bg-gray-200 pointer-events-auto">
          <Plus className="w-3.5 h-3.5" />
        </button>
        <button onClick={() => { try { zoomExtend(); } catch (e) {} }} title="Zoom to full extent" className="p-1 rounded text-gray-600 hover:bg-gray-200 pointer-events-auto">
          <Maximize className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Live on-screen legend - independent of any tool panel state. */}
      <MapLegendPanel
        layersCfg={layersCfg}
        layerOrder={layerOrder}
        layerStyle={layerStyle}
        labelLayers={labelLayers}
        shownTables={legendViewTables}
        expanded={legendExpanded}
        onToggleExpanded={toggleLegend}
        onMove={moveLayer}
      />

      {/* Session-expired banner (e.g. tile 401s after token expiry) */}
      {tileAuthError && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 bg-red-600 text-white rounded-lg shadow-xl px-4 py-2.5 text-sm font-medium flex items-center gap-3">
          <span>Session expired — please log in again.</span>
          <button
            onClick={() => { localStorage.removeItem("token"); window.location.reload(); }}
            className="bg-white text-red-700 rounded px-3 py-1 text-xs font-bold hover:bg-red-50"
          >
            Log in
          </button>
        </div>
      )}

      <Map
        ref={mapRef}
        initialViewState={{ longitude: 31.2, latitude: 30.0, zoom: 11 }}
        onLoad={(ev) => {
          if (ev && ev.target) {
            mapApiRef.current = ev.target;
            // maplibre fires `load` once per style load, so dynamic layers are
            // rebuilt after basemap switches wipe them from the style.
            ev.target.on("load", () => { try { buildDynamic(); } catch (e) { /* none */ } });
            ev.target.on("moveend", scheduleLegendView);
            ev.target.on("sourcedata", (e) => { if (e && e.isSourceLoaded) scheduleLegendView(); });
            scheduleLegendView();
            setMapReady(true);
            zoomExtend();
          }
        }}
        onError={(e) => {
          const st = e && e.error && e.error.status;
          if (st === 401 || st === 403) setTileAuthError(true);
        }}
        onMouseMove={(e) => setCursor(e.lngLat)}
        onMove={(e) => setMapZoom(e.viewState.zoom)}
        mapStyle={BASEMAPS[basemap]}
        interactiveLayerIds={interactiveLayerIds}
        onClick={onClick}
      >
        <DrawControl
          onInit={setDrawInstance}
          displayControlsDefault={false}
          controls={{}}
          onDrawCreate={onUpdateDraw}
          onDrawUpdate={onUpdateDraw}
          onDrawDelete={onDrawDelete}
          onDrawRender={onDrawRender}
        />

        {activeTool === 'measure' && measureSegs.length > 0 && measureSegs.map((s, i) => (
          <Marker key={i} longitude={s.mid[0]} latitude={s.mid[1]} anchor="center">
            <div className="pointer-events-none bg-white border border-indigo-300 text-indigo-700 text-[11px] font-bold px-1.5 py-0.5 rounded shadow-md whitespace-nowrap">
              {formatLength(s.meters, measureMode === 'length' ? measureUnit : 'auto')}
            </div>
          </Marker>
        ))}

        {activeTool === 'measure' && measureMode === 'area' && measureResult && measureResult.type === 'area' && (() => {
          const ring = drawnGeom && drawnGeom.coordinates && drawnGeom.coordinates[0];
          const c = ring ? polygonCentroid(ring) : null;
          if (!c) return null;
          return (
            <Marker longitude={c[0]} latitude={c[1]} anchor="center">
              <div className="pointer-events-none bg-indigo-600 text-white text-xs font-bold px-2 py-1 rounded shadow-lg whitespace-nowrap">
                {formatArea(measureResult.sqm, measureUnit)}
              </div>
            </Marker>
          );
        })()}

        {selectedFeature && (() => {
          const info = layerInfo(selectedFeature.layer);
          const p = selectedFeature.properties || {};
          const FIELD_ORDER = ["Req_Number", "Owner_Name", "Layer_Type", "Area_SQM", "Area_Feddan", "X", "Y", "created_at", "created_by"];
          const COLUMN_LABELS = {
            Req_Number: "Req No", Owner_Name: "Owner", Layer_Type: "Layer Type",
            Area_SQM: "Area (m²)", Area_Feddan: "Area (feddan)", X: "X", Y: "Y",
            created_by: "Added by", created_at: "Added on", id: "ID",
          };
          const prettyKey = (k) => (COLUMN_LABELS[k] || k.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()));
          const fmtValue = (v) => {
            if (v === null || v === undefined || v === "") return null;
            if (typeof v === "number" && Number.isFinite(v)) return v.toLocaleString("en-US", { maximumFractionDigits: 3 });
            if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}[T\s]/.test(v)) {
              const d = new Date(v);
              if (!Number.isNaN(d.getTime())) return d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
            }
            return String(v);
          };
          const keys = [...FIELD_ORDER.filter((k) => k in p), ...Object.keys(p).filter((k) => !FIELD_ORDER.includes(k) && k !== "geometry" && k !== info.geom)];
          const present = keys.filter((k) => fmtValue(p[k]) !== null);
          const area = parseFloat(p.Area_SQM);
          return (
            <Popup
              longitude={selectedFeature.longitude}
              latitude={selectedFeature.latitude}
              anchor="bottom"
              maxWidth="360px"
              onClose={() => setSelectedFeature(null)}
            >
              <div className="min-w-[260px] max-w-[340px]">
                <div className="flex items-center gap-2 pb-2 mb-1 border-b border-gray-100">
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: info.color }} />
                  <h3 className="font-bold text-sm text-gray-800">{info.label}</h3>
                </div>
                {present.map((k) => {
                  const raw = p[k];
                  const rendered = fmtValue(raw);
                  if (k === "Area_SQM") {
                    return (
                      <div key={k} className="flex justify-between gap-3 py-1 border-b border-gray-50">
                        <span className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold pt-0.5">Area</span>
                        <span className="text-xs text-gray-800 text-right">
                          {rendered} m²
                          {Number.isFinite(area) && area > 0 && (
                            <span className="block text-[11px] text-gray-500">{(area / 4200.83).toFixed(4)} feddan</span>
                          )}
                        </span>
                      </div>
                    );
                  }
                  return (
                    <div key={k} className="flex justify-between gap-3 py-1 border-b border-gray-50">
                      <span className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold pt-0.5">{prettyKey(k)}</span>
                      <span className={"text-xs text-right break-all " + (k === "created_by" ? "font-semibold text-blue-700" : "text-gray-800")}>{rendered}</span>
                    </div>
                  );
                })}
              </div>
            </Popup>
          );
        })()}
      </Map>
    </div>
  );
}
