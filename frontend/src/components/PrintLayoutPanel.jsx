import React, { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Map as MlMap } from "maplibre-gl";
import {
  X, Save, FolderOpen, FileDown, RefreshCw, Loader2, AlertTriangle, Move,
  Upload, Compass, Ruler, Grid3x3, AlignLeft, Image as ImageIcon, Undo2, MapPin,
  ChevronDown, ChevronUp, Check
} from "lucide-react";
import { buildPdfFromJpeg, mmToPt } from "../lib/printPdf";

const rawMapOf = (ref) => {
  if (!ref || !ref.current) return null;
  const c = ref.current;
  return (typeof c.getMap === "function" && c.getMap()) || c;
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/* geodesic distance (m) used for the scale bar */
const haversineMeters = (a, b) => {
  const R = 6371008.8;
  const dLat = ((b[1] - a[1]) * Math.PI) / 180;
  const dLng = ((b[0] - a[0]) * Math.PI) / 180;
  const s = Math.sin(dLat / 2) ** 2 +
    Math.cos((a[1] * Math.PI) / 180) * Math.cos((b[1] * Math.PI) / 180) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
};

/* nice step for grids / scale bars from a target value: 1/2/5 x 10^k */
const niceStep = (target) => {
  if (!(target > 0)) return 1;
  const exp = Math.floor(Math.log10(target));
  const base = Math.pow(10, exp);
  const f = target / base;
  if (f > 5) return 10 * base;
  if (f > 2) return 5 * base;
  if (f > 1) return 2 * base;
  return base;
};

const fmtDeg = (v) => (v >= 10 ? v.toFixed(1) : v >= 1 ? v.toFixed(2) : v.toFixed(3));
const coordLabel = (v, axis) =>
  axis === "lng"
    ? fmtDeg(Math.abs(v)) + "\u00b0" + (v >= 0 ? "E" : "W")
    : fmtDeg(Math.abs(v)) + "\u00b0" + (v >= 0 ? "N" : "S");

const TEMPLATES = {
  a4p: { label: "A4 Portrait", wmm: 210, hmm: 297 },
  a4l: { label: "A4 Landscape", wmm: 297, hmm: 210 },
  a3l: { label: "A3 Landscape", wmm: 420, hmm: 297 },
  custom: { label: "Custom", wmm: 297, hmm: 210 },
};
const DPIS = [96, 150, 300];
const PAGE_STORAGE = "printLayoutTemplate";

const dimsOf = (cfg) => {
  const t = TEMPLATES[cfg.template] || TEMPLATES.a4p;
  if (cfg.template === "custom") {
    const wmm = clamp(Number(cfg.customWmm) || 210, 40, 2200);
    const hmm = clamp(Number(cfg.customHmm) || 297, 40, 2200);
    return { wmm, hmm, aspect: wmm / hmm };
  }
  return { wmm: t.wmm, hmm: t.hmm, aspect: t.wmm / t.hmm };
};

const DEFAULT_CFG = {
  template: "a4p",
  customWmm: 297,
  customHmm: 210,
  dpi: 150,
  title: "",
  subtitle: "",
  showTitle: true,
  legendOn: true,
  scaleBarOn: true,
  scaleUnit: "auto",
  northOn: true,
  northStyle: "simple",
  gridOn: false,
  gridStyle: "ticks",      // "ticks" (clean frame defaults) | "lines" (full graticule)
  gridInterval: 0,         // 0 = auto "nice" step; >0 = manual degree interval
  gridMaxLabels: 6,        // target max coordinate labels per border side (auto mode)
  locatorOn: true,
  logoData: null,
  logoPos: "br",
  notesOn: false,
  notesText: "",
};

const HANDLES = [
  { k: "nw", cls: "-top-[6px] -left-[6px]", curs: "cursor-nwse-resize" },
  { k: "n", cls: "-top-[6px] left-1/2 -translate-x-1/2", curs: "cursor-ns-resize" },
  { k: "ne", cls: "-top-[6px] -right-[6px]", curs: "cursor-nesw-resize" },
  { k: "e", cls: "-right-[6px] top-1/2 -translate-y-1/2", curs: "cursor-ew-resize" },
  { k: "se", cls: "-bottom-[6px] -right-[6px]", curs: "cursor-nwse-resize" },
  { k: "s", cls: "-bottom-[6px] left-1/2 -translate-x-1/2", curs: "cursor-ns-resize" },
  { k: "sw", cls: "-bottom-[6px] -left-[6px]", curs: "cursor-nesw-resize" },
  { k: "w", cls: "-left-[6px] top-1/2 -translate-y-1/2", curs: "cursor-ew-resize" },
];

/* Layout math lives in mm so every resolution shares one computation. */
const GRID_GUT = 7; // mm reserved around the map for graticule labels when grid is on

function computeLayout(page, cfg, entries) {
  const M = 8;
  let titleH = 0;
  if (cfg.showTitle && (cfg.title || cfg.subtitle)) {
    titleH += 15;
    if (cfg.subtitle) titleH += 6;
  }
  const footerH = 9;
  const legendRows = entries.length;
  let legendH = 0;
  let legendOverflow = false;
  if (cfg.legendOn && legendRows) {
    const availW = page.wmm - 2 * M;
    const colW = page.wmm / 5;
    const perRow = Math.max(1, Math.floor(availW / colW));
    legendH = Math.ceil(legendRows / perRow) * 7 + 6;
    const cap = 50;
    if (legendH > cap) { legendH = cap; legendOverflow = true; }
  }
  const gut = cfg.gridOn ? GRID_GUT : 0;
  const g2 = 2 * gut;
  const topMax = M + titleH;
  const botMax = page.hmm - M - footerH - legendH;
  const aspect = page.wmm / page.hmm;
  let mapH = botMax - topMax - g2;
  let mapW = Math.min(page.wmm - 2 * M - g2, mapH * aspect);
  mapH = mapW / aspect;
  if (mapH > botMax - topMax - g2) {
    mapH = botMax - topMax - g2;
    mapW = mapH * aspect;
  }
  const mapX = (page.wmm - mapW) / 2;
  const mapY = topMax + (botMax - topMax - mapH) / 2;
  // keep the legend clear of the bottom graticule labels
  const legendTop = mapY + mapH + (gut ? gut + 2 : 3);
  return { M, titleH, footerH, legendH, legendOverflow, gut, mapX, mapY, mapW, mapH, legendTop };
}

const loadImage = (url) =>
  new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = url;
  });

function wrapText(g, text, maxW) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = "";
  for (const w of words) {
    const t = cur ? cur + " " + w : w;
    if (cur && g.measureText(t).width > maxW) {
      lines.push(cur);
      cur = w;
    } else {
      cur = t;
    }
  }
  if (cur) lines.push(cur);
  return lines.length ? lines : [""];
}

function drawGrid(g, K, rect, frameGeo, bearing, gut = 0, cfg = null, pageW = 0, pageH = 0) {
  const lngSpan = frameGeo.maxLng - frameGeo.minLng;
  const latSpan = frameGeo.maxLat - frameGeo.minLat;
  if (lngSpan <= 0 || latSpan <= 0) return;
  const style = cfg && cfg.gridStyle === "lines" ? "lines" : "ticks";
  g.save();
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h / 2;
  const rad = (bearing * Math.PI) / 180;
  g.translate(cx, cy);
  g.rotate(rad);
  g.translate(-cx, -cy);

  // Adaptive label size: smaller frames get smaller labels so more lines fit.
  const baseFont = Math.max(6.5 * K, 8);
  const fontPx = Math.max(6, Math.min(baseFont, rect.w / 16, rect.h / 10));
  g.font = `${fontPx}px sans-serif`;

  // Measure the longest label used in THIS frame for each axis - spacing must
  // never drop below this width or adjacent labels would overlap.
  const lonMag = Math.max(Math.abs(frameGeo.minLng), Math.abs(frameGeo.maxLng), 1);
  const latMag = Math.max(Math.abs(frameGeo.minLat), Math.abs(frameGeo.maxLat), 1);
  const lonLabelW = g.measureText(coordLabel(lonMag, "lng")).width + 2.5 * K;
  const latLabelW = g.measureText(coordLabel(latMag, "lat")).width + 2.5 * K;

  // Interval / density: auto targets a configurable maximum per side using a
  // "nice" round step; a manual override forces an exact degree spacing. The
  // minimum step is bounded by the widest label so text can never collide,
  // no matter how large/panned the extent gets.
  const target = Math.max(2, Math.min(20, Number(cfg && cfg.gridMaxLabels) || 6));
  const manual = Number(cfg && cfg.gridInterval) > 0 ? Number(cfg.gridInterval) : 0;
  let lonStep = manual || niceStep(lngSpan / target);
  let latStep = manual || niceStep(latSpan / target);
  const minLonStep = (lngSpan * lonLabelW) / rect.w;
  const minLatStep = (latSpan * latLabelW) / rect.h;
  lonStep = Math.max(lonStep, minLonStep);
  latStep = Math.max(latStep, minLatStep);

  // Generate ticks with an index loop (avoids float drift on repeated add).
  // A value whose coordinate would fall OUTSIDE the frame's extent is omitted
  // entirely - never drawn partially off the frame edge.
  const mk = (start, step, min, max) => {
    const n = Math.ceil((max - start) / step - 1e-9);
    const out = [];
    for (let i = 0; i <= n; i++) {
      const v = start + i * step;
      if (v >= min - 1e-9 && v <= max + 1e-9) out.push(v);
    }
    return out;
  };
  const lons = mk(
    Math.floor(frameGeo.minLng / lonStep) * lonStep, lonStep,
    frameGeo.minLng, frameGeo.maxLng,
  );
  const lats = mk(
    Math.floor(frameGeo.minLat / latStep) * latStep, latStep,
    frameGeo.minLat, frameGeo.maxLat,
  );

  if (style === "lines") {
    // Full graticule: coordinate lines drawn across the whole map content.
    const span = Math.max(rect.w, rect.h) * 1.6;
    g.strokeStyle = "rgba(15,23,42,0.28)";
    g.lineWidth = Math.max(1, K * 0.5);
    g.save();
    g.beginPath();
    g.rect(rect.x, rect.y, rect.w, rect.h);
    g.clip();
    for (const v of lons) {
      const xx = rect.x + ((v - frameGeo.minLng) / lngSpan) * rect.w;
      g.beginPath();
      g.moveTo(xx, cy - span);
      g.lineTo(xx, cy + span);
      g.stroke();
    }
    for (const v of lats) {
      const yy = rect.y + ((frameGeo.maxLat - v) / latSpan) * rect.h;
      g.beginPath();
      g.moveTo(cx - span, yy);
      g.lineTo(cx + span, yy);
      g.stroke();
    }
    g.restore();
  } else {
    // Tick marks only: nobody draws on the map content - a short dash on the
    // frame border marks every coordinate, keeping the interior completely clean.
    const tickLen = Math.max(3, 0.6 * K);
    g.strokeStyle = "#475569";
    g.lineWidth = Math.max(1, K * 0.6);
    for (const v of lons) {
      const xx = rect.x + ((v - frameGeo.minLng) / lngSpan) * rect.w;
      g.beginPath();
      g.moveTo(xx, rect.y - tickLen);
      g.lineTo(xx, rect.y + tickLen);
      g.stroke();
      g.beginPath();
      g.moveTo(xx, rect.y + rect.h - tickLen);
      g.lineTo(xx, rect.y + rect.h + tickLen);
      g.stroke();
    }
    for (const v of lats) {
      const yy = rect.y + ((frameGeo.maxLat - v) / latSpan) * rect.h;
      g.beginPath();
      g.moveTo(rect.x - tickLen, yy);
      g.lineTo(rect.x + tickLen, yy);
      g.stroke();
      g.beginPath();
      g.moveTo(rect.x + rect.w - tickLen, yy);
      g.lineTo(rect.x + rect.w + tickLen, yy);
      g.stroke();
    }
  }

  // Labels always sit OUTSIDE the frame outline, never over the map content.
  // Placement follows the border side: horizontal on top/bottom, rotated 90deg
  // (parallel to the border) on left/right, each centered on its tick/line.
  const gap = 1.4 * K;
  const go = gut ? gut * K : gap;
  const edge = 2; // px hard margin from the printable page edge
  g.fillStyle = "#334155";

  // Top + bottom: longitude labels, horizontal, centered on each position.
  // Any label whose box would leave the printable page is omitted (never
  // clipped or drawn partially).
  g.textAlign = "center";
  for (const v of lons) {
    const xx = rect.x + ((v - frameGeo.minLng) / lngSpan) * rect.w;
    const lb = coordLabel(v, "lng");
    if (xx < edge + 6 || xx > pageW - edge - 6) continue;
    if (rect.y - gap - fontPx >= edge) {
      g.textBaseline = "alphabetic";
      g.fillText(lb, xx, rect.y - gap);
    }
    if (rect.y + rect.h + gap + fontPx <= pageH - edge) {
      g.textBaseline = "top";
      g.fillText(lb, xx, rect.y + rect.h + gap);
    }
  }

  // Left + right: latitude labels rotated 90deg so the text runs parallel to
  // the border, reading bottom-to-top, anchored just outside the outline.
  // Every label must fit fully inside the printable page - anything that would
  // be clipped is omitted entirely (never drawn partially).
  g.textAlign = "left";
  g.textBaseline = "alphabetic";
  for (const v of lats) {
    const yy = rect.y + ((frameGeo.maxLat - v) / latSpan) * rect.h;
    const lb = coordLabel(v, "lat");
    const tw = g.measureText(lb).width;
    const yT = yy - tw / 2;
    const yB = yy + tw / 2;
    const inV = yT >= edge + 4 && yB <= pageH - edge - 4;
    if (inV && rect.x - go - fontPx >= edge) {
      g.save();
      g.translate(rect.x - go, yy + tw / 2);
      g.rotate(-Math.PI / 2);
      g.fillText(lb, 0, 0);
      g.restore();
    }
    if (inV && rect.x + rect.w + go + 2.5 * fontPx <= pageW - edge) {
      g.save();
      g.translate(rect.x + rect.w + go + fontPx, yy + tw / 2);
      g.rotate(-Math.PI / 2);
      g.fillText(lb, 0, 0);
      g.restore();
    }
  }
  g.restore();
}

function drawScaleBar(g, K, rect, frameGeo, unit) {
  const cY = (frameGeo.minLat + frameGeo.maxLat) / 2;
  const metersAcross = haversineMeters([frameGeo.minLng, cY], [frameGeo.maxLng, cY]);
  if (!(metersAcross > 0)) return;
  const mpp = metersAcross / rect.w;
  const nice = niceStep(metersAcross * 0.34);
  let label;
  if (unit === "mi") {
    const mi = nice / 1609.344;
    label = mi >= 5 ? mi.toFixed(0) + " miles" : mi.toFixed(2) + " mi";
  } else if (unit === "km") label = nice / 1000 + " km";
  else if (unit === "m") label = nice + " m";
  else label = nice >= 1000 ? nice / 1000 + " km" : nice + " m";
  const barPx = nice / mpp;
  if (barPx <= 12) return;
  const x0 = rect.x + rect.w / 2 - barPx / 2;
  const y = rect.y + rect.h - 6.5 * K;
  const barH = 2.6 * K;
  g.save();
  g.fillStyle = "rgba(255,255,255,0.85)";
  g.fillRect(x0 - 2 * K, y - 2 * K, barPx + 4 * K, barH + 6 * K);
  const seg = barPx / 2;
  g.fillStyle = "#000";
  g.fillRect(x0, y, seg, barH);
  g.fillStyle = "#fff";
  g.fillRect(x0 + seg, y, seg, barH);
  g.strokeStyle = "#000";
  g.lineWidth = Math.max(1, K * 0.6);
  g.strokeRect(x0, y, barPx, barH);
  for (let i = 0; i <= 2; i++) {
    const tx = x0 + seg * i;
    g.beginPath();
    g.moveTo(tx, y);
    g.lineTo(tx, y + barH);
    g.stroke();
  }
  g.fillStyle = "#0f172a";
  g.font = `600 ${Math.max(3.2 * K, 5)}px sans-serif`;
  g.textAlign = "center";
  g.textBaseline = "alphabetic";
  g.fillText(label, x0 + barPx / 2, y + barH + 4 * K);
  g.restore();
}

function drawNorthArrow(g, K, x, y, bearing, style) {
  g.save();
  g.translate(x, y);
  g.rotate((-bearing * Math.PI) / 180);
  const s = Math.max(5, 6 * K);
  g.strokeStyle = "#64748b";
  if (style === "full") {
    g.beginPath();
    g.arc(0, 0, s, 0, Math.PI * 2);
    g.fillStyle = "rgba(255,255,255,0.9)";
    g.fill();
    g.lineWidth = K * 0.5;
    g.stroke();
    g.strokeStyle = "#94a3b8";
    [[0, -s], [s, 0], [0, s], [-s, 0]].forEach(([dx, dy]) => {
      g.beginPath();
      g.moveTo(dx, dy);
      g.lineTo(dx * 0.72, dy * 0.72);
      g.stroke();
    });
    g.font = `bold ${Math.max(3 * K, 5)}px sans-serif`;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillStyle = "#b91c1c";
    g.fillText("N", 0, -s * 0.66);
    g.fillStyle = "#475569";
    g.fillText("E", s * 0.74, 0);
    g.fillText("S", 0, s * 0.8);
    g.fillText("W", -s * 0.77, 0);
  } else {
    g.beginPath();
    g.arc(0, 0, s, 0, Math.PI * 2);
    g.fillStyle = "rgba(255,255,255,0.9)";
    g.fill();
    g.lineWidth = K * 0.6;
    g.stroke();
    g.beginPath();
    g.moveTo(0, -s * 0.55);
    g.lineTo(s * 0.3, s * 0.42);
    g.lineTo(0, 0);
    g.lineTo(-s * 0.3, s * 0.42);
    g.closePath();
    g.fillStyle = "#b91c1c";
    g.fill();
    g.strokeStyle = "#7f1d1d";
    g.lineWidth = K * 0.4;
    g.stroke();
    g.fillStyle = "#b91c1c";
    g.font = `bold ${Math.max(3.4 * K, 5)}px sans-serif`;
    g.textAlign = "center";
    g.textBaseline = "alphabetic";
    g.fillText("N", 0, -s * 0.7);
  }
  g.restore();
}

function drawLocator(g, K, rect, frameGeo, fullExtent) {
  if (!fullExtent || fullExtent.length !== 4) return;
  const [minLng, minLat, maxLng, maxLat] = fullExtent;
  const eW = Math.max(1e-6, maxLng - minLng);
  const eH = Math.max(1e-6, maxLat - minLat);
  const boxW = 19 * K;
  const boxH = 23 * K;
  const x = rect.x + rect.w - boxW - 3.5 * K;
  const y = rect.y + rect.h - boxH - 3.5 * K;
  g.save();
  g.fillStyle = "rgba(255,255,255,0.92)";
  g.fillRect(x - 2 * K, y - 2 * K, boxW + 4 * K, boxH + 4 * K);
  g.strokeStyle = "#94a3b8";
  g.lineWidth = K * 0.5;
  g.strokeRect(x - 2 * K, y - 2 * K, boxW + 4 * K, boxH + 4 * K);
  g.strokeStyle = "#64748b";
  g.strokeRect(x, y, boxW, boxH);
  const fx = x + ((frameGeo.minLng - minLng) / eW) * boxW;
  const fy = y + ((maxLat - frameGeo.maxLat) / eH) * boxH;
  const fw = ((frameGeo.maxLng - frameGeo.minLng) / eW) * boxW;
  const fh = ((frameGeo.maxLat - frameGeo.minLat) / eH) * boxH;
  g.fillStyle = "rgba(30,64,175,0.4)";
  g.fillRect(fx, fy, Math.max(2, fw), Math.max(2, fh));
  g.strokeStyle = "#1e40af";
  g.lineWidth = K * 0.7;
  g.strokeRect(fx, fy, Math.max(2, fw), Math.max(2, fh));
  g.setLineDash([2 * K, 2 * K]);
  g.strokeStyle = "#334155";
  g.lineWidth = K * 0.4;
  g.beginPath();
  g.moveTo(x + boxW / 2, y);
  g.lineTo(x + boxW / 2, y + boxH);
  g.moveTo(x, y + boxH / 2);
  g.lineTo(x + boxW, y + boxH / 2);
  g.stroke();
  g.restore();
}

function drawTitle(g, K, cfg, layout, page, W) {
  if (layout.titleH <= 0) return;
  const y = layout.M * K;
  g.textAlign = "center";
  g.textBaseline = "alphabetic";
  if (cfg.title) {
    g.font = `bold ${7 * K}px system-ui, sans-serif`;
    g.fillStyle = "#0f172a";
    g.fillText(cfg.title, W / 2, y + 5.4 * K);
  }
  if (cfg.subtitle) {
    g.font = `${4.2 * K}px system-ui, sans-serif`;
    g.fillStyle = "#475569";
    g.fillText(cfg.subtitle, W / 2, y + (cfg.title ? 10.8 : 5) * K);
  }
}

function drawLegend(g, K, layout, page, cfg, entries) {
  const x = layout.M * K;
  const y = layout.legendTop * K;
  const availW = (page.wmm - 2 * layout.M) * K;
  const colW = page.wmm / 5 * K;
  const perRow = Math.max(1, Math.floor(availW / colW));
  const rowH = 6.6 * K;
  const sw = 6 * K;
  g.save();
  g.font = `bold ${4.4 * K}px sans-serif`;
  g.fillStyle = "#0f172a";
  g.textAlign = "left";
  g.textBaseline = "alphabetic";
  g.fillText("Legend", x, y + rowH - 1 * K);
  let col = 0;
  let row = 0;
  entries.forEach((e) => {
    const colX = x + col * colW;
    const rowY = y + rowH + row * rowH;
    const isPoint = /POINT/.test(e.gtype || "");
    const isLine = /LINE/.test(e.gtype || "");
    if (isPoint) {
      g.fillStyle = e.color;
      g.beginPath();
      g.arc(colX + sw / 2, rowY + sw / 2, sw / 2, 0, Math.PI * 2);
      g.fill();
    } else if (isLine) {
      g.strokeStyle = e.color;
      g.lineWidth = 1.6 * K;
      g.beginPath();
      g.moveTo(colX, rowY + sw / 2);
      g.lineTo(colX + sw, rowY + sw / 2);
      g.stroke();
    } else {
      g.fillStyle = e.color;
      g.fillRect(colX, rowY + 0.4 * K, sw, sw);
    }
    g.fillStyle = "#334155";
    g.font = `${Math.max(3.8 * K, 5)}px sans-serif`;
    g.textAlign = "left";
    g.textBaseline = "middle";
    const label = e.label.length > 24 ? e.label.slice(0, 23) + "\u2026" : e.label;
    g.fillText(label, colX + sw + 2.4 * K, rowY + sw / 2 + 0.4 * K);
    col++;
    if (col >= perRow) { col = 0; row++; }
  });
  if (cfg.legendNote) {
    g.font = `${Math.max(3 * K, 5)}px sans-serif`;
    g.fillStyle = "#94a3b8";
    g.textAlign = "left";
    g.fillText(cfg.legendNote, x, y + rowH + (row + 1) * rowH + 0.5 * K);
  }
  g.restore();
}

function drawNotes(g, K, cfg, layout, page, W) {
  const y = (page.hmm - layout.footerH / 2) * K;
  g.font = `${Math.max(3.5 * K, 5)}px sans-serif`;
  g.fillStyle = "#475569";
  g.textAlign = "center";
  g.textBaseline = "middle";
  const maxW = (page.wmm - 2 * layout.M) * K;
  const lines = wrapText(g, cfg.notesText, maxW);
  lines.forEach((ln, i) => {
    g.fillText(ln, W / 2, y + (i - (lines.length - 1) / 2) * 4.6 * K);
  });
}

function drawLogo(g, K, cfg, page, W, H, logoImg) {
  if (!logoImg || !logoImg.width) return;
  const maxH = 13 * K;
  const maxW = 44 * K;
  const h = maxH;
  const w = Math.min(maxW, h * (logoImg.width / logoImg.height));
  const m = 10 * K;
  const pos = cfg.logoPos || "br";
  let x = pos.includes("l") ? m : W - m - w;
  let y = pos.includes("t") ? m : H - m - h;
  g.save();
  g.globalAlpha = 0.95;
  g.drawImage(logoImg, x, y, w, h);
  g.restore();
}

/* Render the composed print page to a canvas. */
async function renderPage({ cfg, page, layout, mapUrl, bearing, frameGeo, legendEntries, fullExtent, dpi, logoImg }) {
  const K = dpi / 25.4;
  const W = Math.max(2, Math.round(page.wmm * K));
  const H = Math.max(2, Math.round(page.hmm * K));
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const g = canvas.getContext("2d");
  g.fillStyle = "#ffffff";
  g.fillRect(0, 0, W, H);
  const img = await loadImage(mapUrl);
  const rect = { x: layout.mapX * K, y: layout.mapY * K, w: layout.mapW * K, h: layout.mapH * K };
  if (img) g.drawImage(img, rect.x, rect.y, rect.w, rect.h);
  g.strokeStyle = "#111827";
  g.lineWidth = Math.max(1, 1.1 * K);
  g.strokeRect(rect.x, rect.y, rect.w, rect.h);
  if (cfg.gridOn) drawGrid(g, K, rect, frameGeo, bearing, layout.gut, cfg, W, H);
  if (cfg.scaleBarOn) drawScaleBar(g, K, rect, frameGeo, cfg.scaleUnit);
  if (cfg.northOn) drawNorthArrow(g, K, rect.x + rect.w - 12 * K, rect.y + 11 * K, bearing, cfg.northStyle);
  if (cfg.locatorOn) drawLocator(g, K, rect, frameGeo, fullExtent);
  if (cfg.showTitle) drawTitle(g, K, cfg, layout, page, W);
  if (cfg.legendOn && legendEntries.length) drawLegend(g, K, layout, page, cfg, legendEntries);
  if (cfg.notesOn && cfg.notesText) drawNotes(g, K, cfg, layout, page, W);
  if (cfg.logoData) drawLogo(g, K, cfg, page, W, H, logoImg);
  g.strokeStyle = "#94a3b8";
  g.lineWidth = K * 0.9;
  g.strokeRect(5 * K, 5 * K, W - 10 * K, H - 10 * K);
  return canvas;
}

const canvasToBlob = (canvas, type, q) =>
  new Promise((resolve) => canvas.toBlob((b) => resolve(b), type, q));

const stamp = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
};

function ResizeHandle({ width, min, max, onWidth }) {
  const start = useRef(null);
  const onPointerDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    start.current = { x: e.clientX, w: width };
    const move = (ev) => {
      if (!start.current) return;
      onWidth(Math.max(min, Math.min(max, start.current.w - (ev.clientX - start.current.x))));
    };
    const up = () => {
      start.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <div
      onPointerDown={onPointerDown}
      className="absolute left-0 inset-y-0 w-1.5 cursor-ew-resize select-none flex items-center justify-center group"
      style={{ touchAction: "none" }}
      title="Drag to resize"
    >
      <div className="w-[3px] h-10 rounded-full bg-gray-300/70 group-hover:bg-blue-500 transition-colors" />
    </div>
  );
}

function Section({ title, icon, open, onToggle, children }) {
  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden">
      <button onClick={onToggle} className="w-full flex items-center justify-between px-2.5 py-2 bg-gray-50 text-left">
        <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider flex items-center gap-1.5">
          {icon}
          {title}
        </span>
        {open ? <ChevronUp className="w-3.5 h-3.5 text-gray-400" /> : <ChevronDown className="w-3.5 h-3.5 text-gray-400" />}
      </button>
      {open && <div className="p-2.5 space-y-2">{children}</div>}
    </div>
  );
}

const CheckRow = ({ checked, onChange, label }) => (
  <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer py-0.5">
    <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
    {label}
  </label>
);

export default function PrintLayoutPanel({
  mapRef, basemapStyle, buildDynamic, layersCfg = [], layerOrder = [], layerStyle = {}, layerVisibility = {},
  fullExtent = null, onClose, panelWidth = 400, onPanelWidth = () => {},
}) {
  const buildDynamicRef = useRef(buildDynamic);
  buildDynamicRef.current = buildDynamic;
  const fullExtentRef = useRef(fullExtent);
  fullExtentRef.current = fullExtent;

  const [cfg, setCfg] = useState(() => {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(PAGE_STORAGE) || "null"); } catch (e) { saved = null; }
    const base = { ...DEFAULT_CFG };
    if (saved && saved.cfg && typeof saved.cfg === "object") Object.assign(base, saved.cfg);
    return base;
  });
  const [frame, setFrame] = useState(() => {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(PAGE_STORAGE) || "null"); } catch (e) { saved = null; }
    if (saved && saved.frame && saved.frame.w > 0 && saved.frame.h > 0) return saved.frame;
    return null;
  });
  const [warn, setWarn] = useState("");
  const [busy, setBusy] = useState("idle");
  const [preview, setPreview] = useState(null);
  const [previewReady, setPreviewReady] = useState(false);
  const [geomTick, setGeomTick] = useState(0);
  const [mapReady, setMapReady] = useState(false);
  const [legendViewTables, setLegendViewTables] = useState(null);
  const [sections, setSections] = useState({ page: true, elements: true, preview: true });

  const page = useMemo(() => dimsOf(cfg), [cfg]);
  const cfgDimRef = useRef(page);
  cfgDimRef.current = page;
  const stateRef = useRef({});
  stateRef.current = { cfg, frame, page, mapReady };

  const prevSigRef = useRef("");
  const seqRef = useRef(0);
  const capBusyRef = useRef(false);
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const logoImgRef = useRef(null);
  const logoLoadTickRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let cleanup = null;
    const tryBind = () => {
      const map = rawMapOf(mapRef);
      if (!map) {
        timer = setTimeout(tryBind, 400);
        return;
      }
      if (cancelled) return;
      setMapReady(true);
      const onMove = () => setGeomTick((t) => t + 1);
      map.on("moveend", onMove);
      cleanup = () => map.off("moveend", onMove);
    };
    tryBind();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (cleanup) cleanup();
    };
  }, [mapRef]);

  /* like the live legend tool: a print-legend entry is shown only for layers
     that actually have features rendered inside the frame region on the map. */
  const legendScanTimer = useRef(null);
  useEffect(() => {
    if (!mapReady) return;
    clearTimeout(legendScanTimer.current);
    legendScanTimer.current = setTimeout(() => {
      try {
        const map = rawMapOf(mapRef);
        if (!map || typeof map.queryRenderedFeatures !== "function") return;
        if (!frame || frame.w <= 0.001 || frame.h <= 0.001) { setLegendViewTables(null); return; }
        const cont = map.getContainer();
        const cw = cont.clientWidth || 1;
        const ch = cont.clientHeight || 1;
        const corners = [
          [frame.x * cw, frame.y * ch],
          [(frame.x + frame.w) * cw, frame.y * ch],
          [(frame.x + frame.w) * cw, (frame.y + frame.h) * ch],
          [frame.x * cw, (frame.y + frame.h) * ch],
        ];
        const xs = corners.map((p) => p[0]);
        const ys = corners.map((p) => p[1]);
        const bbox = [[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]];
        const feats = map.queryRenderedFeatures(bbox, {});
        const present = new Set(feats.map((ft) => ft.source).filter((s) => layerVisibility[s]));
        const ordered = orderedTables.filter((t) => present.has(t));
        setLegendViewTables(ordered);
      } catch (e) { setLegendViewTables(null); }
    }, 250);
    return () => { if (legendScanTimer.current) clearTimeout(legendScanTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapReady, frame, geomTick, layerVisibility, layerOrder]);

  /* default frame on first open: largest page-aspect rect fitting the viewport */
  const fitFrame = useCallback((ratio = 0.9) => {
    const { wmm, hmm } = cfgDimRef.current;
    const map = rawMapOf(mapRef);
    const cont = map && map.getContainer();
    const cw = cont ? cont.clientWidth : 800;
    const ch = cont ? cont.clientHeight : 600;
    const contAspect = cw / ch;
    const pageAspect = wmm / hmm;
    let w, h;
    if (pageAspect >= contAspect) { w = ratio; h = w / pageAspect; }
    else { h = ratio; w = h * pageAspect; }
    setFrame({ x: (1 - w) / 2, y: (1 - h) / 2, w, h });
  }, [mapRef]);

  /* recompute the on-screen frame when the page aspect changes (keep area + center). */
  const recomputeForTemplate = useCallback((wmm2, hmm2) => {
    setFrame((prev) => {
      if (!prev) return prev;
      const aspect = wmm2 / hmm2;
      const area = (prev.w * prev.h) || 0.16;
      let nw = Math.sqrt(area * aspect);
      let nh = nw / aspect;
      if (nw > 0.92) { nw = 0.92; nh = nw / aspect; }
      if (nh > 0.92) { nh = 0.92; nw = nh * aspect; }
      const x = clamp(0.5 - nw / 2, -0.02, 1.02 - nw);
      const y = clamp(0.5 - nh / 2, -0.02, 1.02 - nh);
      return { x, y, w: nw, h: nh };
    });
  }, []);

  useEffect(() => {
    if (!frame) {
      const t = setTimeout(() => fitFrame(), 50);
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame]);

  const setTemplate = (t) => {
    const td = TEMPLATES[t] || TEMPLATES.a4p;
    const next = { ...cfg, template: t };
    if (t === "custom") next.customWmm = cfg.customWmm || td.wmm;
    if (t === "custom") next.customHmm = cfg.customHmm || td.hmm;
    setCfg(next);
    recomputeForTemplate(dimsOf(next).wmm, dimsOf(next).hmm);
  };
  const setCustom = (field, val) => {
    const nv = clamp(Number(val) || 1, 40, 2200);
    const next = { ...cfg, [field]: nv };
    setCfg(next);
    recomputeForTemplate(dimsOf(next).wmm, dimsOf(next).hmm);
  };

  /* legend entries = visible layers in the print frame, ordered; before the
     first view-scan resolves, behave as "visible layers". */
  const labelOf = useCallback((t) => {
    const c = layersCfg.find((l) => l.table === t);
    return c ? c.label : t;
  }, [layersCfg]);
  const gtypeOf = useCallback((t) => {
    const c = layersCfg.find((l) => l.table === t);
    return c ? c.gtype : "";
  }, [layersCfg]);
  const orderedTables = useMemo(() => {
    const byOrder = [...layersCfg].sort((a, b) => layerOrder.indexOf(a.table) - layerOrder.indexOf(b.table));
    return byOrder.map((l) => l.table);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layersCfg, layerOrder]);
  const legendEntries = useMemo(() =>
    orderedTables
      .filter((t) => layerVisibility[t] && (legendViewTables === null || legendViewTables.includes(t)))
      .map((t) => ({
        table: t,
        label: labelOf(t),
        color: (layerStyle[t] && layerStyle[t].color) || "#3388ff",
        gtype: gtypeOf(t),
      })),
  [orderedTables, layerVisibility, layerStyle, labelOf, gtypeOf, legendViewTables]);
  const legendEntriesRef = useRef(legendEntries);
  legendEntriesRef.current = legendEntries;

  /* approximate map scale at the frame, shown in the footer */
  const scaleX = useMemo(() => {
    const map = rawMapOf(mapRef);
    if (!map || !frame || !mapReady) return null;
    try {
      const cont = map.getContainer();
      const cw = cont.clientWidth || 1;
      const ch = cont.clientHeight || 1;
      const yc = (frame.y + frame.h / 2) * ch;
      const west = map.unproject([frame.x * cw, yc]);
      const east = map.unproject([(frame.x + frame.w) * cw, yc]);
      const meters = haversineMeters([west.lng, west.lat], [east.lng, east.lat]);
      const layout = computeLayout(page, cfg, legendEntries);
      if (!(layout.mapW > 0) || !(meters > 0)) return null;
      return Math.round((meters * 1000) / layout.mapW);
    } catch (e) {
      return null;
    }
  }, [mapRef, frame, page, cfg, mapReady, geomTick, legendEntries]);

  /* logo image element */
  useEffect(() => {
    logoImgRef.current = null;
    if (!cfg.logoData) return;
    const im = new Image();
    im.onload = () => {
      logoImgRef.current = im;
      logoLoadTickRef.current += 1;
      setGeomTick((t) => t + 1);
    };
    im.src = cfg.logoData;
  }, [cfg.logoData]);

  const captureFrom = useCallback((pxW, pxH) => new Promise((resolve) => {
    const map = rawMapOf(mapRef);
    if (!map || typeof map.unproject !== "function") return resolve(null);
    const st = stateRef.current;
    const f = st.frame;
    if (!f || f.w <= 0.001 || f.h <= 0.001) return resolve(null);
    const cont = map.getContainer();
    const cw = cont.clientWidth || 1;
    const ch = cont.clientHeight || 1;
    let corners;
    try {
      corners = [
        [f.x * cw, f.y * ch],
        [(f.x + f.w) * cw, f.y * ch],
        [(f.x + f.w) * cw, (f.y + f.h) * ch],
        [f.x * cw, (f.y + f.h) * ch],
      ].map(([x, y]) => map.unproject([x, y]));
    } catch (e) { return resolve(null); }
    const lngs = corners.map((c) => c.lng);
    const lats = corners.map((c) => c.lat);
    const frameGeo = {
      minLng: Math.min(...lngs),
      maxLng: Math.max(...lngs),
      minLat: Math.min(...lats),
      maxLat: Math.max(...lats),
    };
    const bearing = map.getBearing();
    const el = document.createElement("div");
    el.style.cssText = `position:fixed;left:-99999px;top:0;width:${pxW}px;height:${pxH}px;pointer-events:none;`;
    document.body.appendChild(el);
    let done = false;
    let mapInst = null;
    const finish = () => {
      if (done) return;
      done = true;
      let url = null;
      try { if (mapInst) url = mapInst.getCanvas().toDataURL("image/png"); } catch (e) { url = null; }
      try { if (mapInst) mapInst.remove(); } catch (e) { /* noop */ }
      el.remove();
      resolve(url ? { dataUrl: url, bearing, frameGeo } : null);
    };
    try {
      mapInst = new MlMap({
        container: el,
        style: basemapStyle,
        preserveDrawingBuffer: true,
        interactive: false,
        attributionControl: false,
        bearing,
        pitch: 0,
        antialias: true,
      });
    } catch (e) { return finish(); }
    mapInst.on("load", () => {
      try { if (buildDynamicRef.current) buildDynamicRef.current(mapInst); } catch (e) { /* noop */ }
      try {
        mapInst.fitBounds([[frameGeo.minLng, frameGeo.minLat], [frameGeo.maxLng, frameGeo.maxLat]], { padding: 0, duration: 0 });
      } catch (e) { /* noop */ }
      // give the fresh map a moment, then wait until every tile is actually
      // present before capturing - `idle` alone fires before tiles finish
      // loading, which yields a blank (all-white) page.
      setTimeout(() => {
        const waitTiles = () => {
          if (done || !mapInst) return;
          try {
            if (typeof mapInst.areTilesLoaded === "function" && !mapInst.areTilesLoaded()) {
              setTimeout(waitTiles, 300);
              return;
            }
            mapInst.once("idle", () => setTimeout(finish, 120));
            mapInst.triggerRepaint();
          } catch (e) {
            finish();
          }
        };
        waitTiles();
      }, 200);
    });
    mapInst.on("error", () => { /* keep waiting for load/tiles or timeout */ });
    setTimeout(finish, 12000);
  }), [mapRef, basemapStyle]);

  /* resolve the capture geometry + rebuild previews when signatures change */
  const previewSig = useMemo(() => JSON.stringify({
    frame, page, dpi: cfg.dpi, title: cfg.title, subtitle: cfg.subtitle, showTitle: cfg.showTitle,
    legendOn: cfg.legendOn, scaleBarOn: cfg.scaleBarOn, scaleUnit: cfg.scaleUnit,
    northOn: cfg.northOn, northStyle: cfg.northStyle, gridOn: cfg.gridOn, gridStyle: cfg.gridStyle,
    gridInterval: cfg.gridInterval, gridMaxLabels: cfg.gridMaxLabels, locatorOn: cfg.locatorOn,
    logoData: cfg.logoData, logoPos: cfg.logoPos, notesOn: cfg.notesOn, notesText: cfg.notesText,
    geomTick, entries: legendEntries.map((e) => e.label + e.color + e.gtype).join("|"), fullExtent,
  }), [frame, page, cfg, geomTick, legendEntries, fullExtent]);

  const doRender = useCallback(async (asPreview) => {
    if (capBusyRef.current) return;
    if (busyRef.current === "exporting") return;
    capBusyRef.current = true;
    const st = stateRef.current;
    setBusy(asPreview ? "preview" : "exporting");
    setWarn((w) => (asPreview ? w : ""));
    const token = ++seqRef.current;
    try {
      const layout = computeLayout(st.page, st.cfg, legendEntriesRef.current);
      const PXS = (asPreview ? 96 : st.cfg.dpi) / 25.4;
      const pxW = Math.max(2, Math.round(layout.mapW * PXS));
      const pxH = Math.max(2, Math.round(layout.mapH * PXS));
      const cap = await captureFrom(pxW, pxH);
      if (token !== seqRef.current) return;
      if (!cap) { setBusy("idle"); return; }
      const canvas = await renderPage({
        cfg: st.cfg, page: st.page, layout,
        mapUrl: cap.dataUrl, bearing: cap.bearing, frameGeo: cap.frameGeo,
        legendEntries: legendEntriesRef.current, fullExtent: fullExtentRef.current,
        dpi: asPreview ? 96 : st.cfg.dpi, logoImg: logoImgRef.current,
      });
      if (token !== seqRef.current) return;
      setPreview(canvas.toDataURL("image/jpeg", asPreview ? 0.82 : 0.92));
      setPreviewReady(true);
    } catch (e) {
      if (token === seqRef.current) setWarn("Preview failed: " + (e && e.message ? e.message : "render error"));
    } finally {
      if (token === seqRef.current) { capBusyRef.current = false; setBusy("idle"); }
      else capBusyRef.current = false;
    }
  }, [captureFrom]);

  /* auto-refresh preview (debounced) when signature changes */
  useEffect(() => {
    if (!mapReady) return;
    if (busyRef.current === "exporting") return;
    if (previewSig === prevSigRef.current) return;
    prevSigRef.current = previewSig;
    const t = setTimeout(() => doRender(true), 300);
    return () => clearTimeout(t);
  }, [previewSig, mapReady, doRender]);

  const forceRefresh = () => {
    prevSigRef.current = "";
    setGeomTick((t) => t + 1);
  };

  const downloadBlob = (name, blob) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  };

  const doExport = async (fmt) => {
    if (busy !== "idle") return;
    const st = stateRef.current;
    const map = rawMapOf(mapRef);
    if (!map) { setWarn("Map is not ready yet."); return; }
    if (!st.frame || st.frame.w <= 0.02 || st.frame.h <= 0.06) {
      setWarn("Print frame is too small - enlarge it on the map first.");
      return;
    }
    setBusy("exporting");
    setWarn("");
    try {
      try {
        if (map.areTilesLoaded && !map.areTilesLoaded()) {
          setWarn("Some tiles are still loading; the output may be incomplete.");
        }
      } catch (e) { /* noop */ }
      const layout = computeLayout(st.page, st.cfg, legendEntriesRef.current);
      const PXS = st.cfg.dpi / 25.4;
      const pxW = Math.max(2, Math.round(layout.mapW * PXS));
      const pxH = Math.max(2, Math.round(layout.mapH * PXS));
      const token = ++seqRef.current;
      const cap = await captureFrom(pxW, pxH);
      if (token !== seqRef.current) return;
      if (!cap) { setWarn("Could not render the map for export. Try again."); return; }
      const canvas = await renderPage({
        cfg: st.cfg, page: st.page, layout,
        mapUrl: cap.dataUrl, bearing: cap.bearing, frameGeo: cap.frameGeo,
        legendEntries: legendEntriesRef.current, fullExtent: fullExtentRef.current,
        dpi: st.cfg.dpi, logoImg: logoImgRef.current,
      });
      if (fmt === "png") {
        const blob = await canvasToBlob(canvas, "image/png");
        if (blob) downloadBlob(`print_${stamp()}.png`, blob);
      } else if (fmt === "jpeg") {
        const blob = await canvasToBlob(canvas, "image/jpeg", 0.92);
        if (blob) downloadBlob(`print_${stamp()}.jpg`, blob);
      } else {
        const jpeg = canvas.toDataURL("image/jpeg", 0.92);
        const bytes = buildPdfFromJpeg({
          jpegDataUrl: jpeg,
          widthPx: canvas.width,
          heightPx: canvas.height,
          pageWidthPt: mmToPt(st.page.wmm),
          pageHeightPt: mmToPt(st.page.hmm),
        });
        downloadBlob(`print_${stamp()}.pdf`, new Blob([bytes], { type: "application/pdf" }));
      }
    } catch (e) {
      setWarn("Export failed: " + (e && e.message ? e.message : "unknown error"));
    } finally {
      setBusy("idle");
    }
  };

  const saveTemplate = () => {
    try {
      localStorage.setItem(PAGE_STORAGE, JSON.stringify({ cfg, frame }));
      setWarn("Template saved for next time.");
    } catch (e) {
      setWarn("Could not save template (logo image may be too large).");
    }
  };
  const resetTemplate = () => {
    setCfg((prev) => ({ ...DEFAULT_CFG }));
    const d = dimsOf(DEFAULT_CFG);
    recomputeForTemplate(d.wmm, d.hmm);
    setWarn("");
  };

  const startResize = (e, mode) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const map = rawMapOf(mapRef);
    const cont = map && map.getContainer();
    const cw = cont ? cont.clientWidth : 800;
    const ch = cont ? cont.clientHeight : 600;
    const base = stateRef.current.frame || { x: 0.2, y: 0.2, w: 0.5, h: 0.5 };
    const sx = e.clientX;
    const sy = e.clientY;
    const aspect = cfgDimRef.current.wmm / cfgDimRef.current.hmm;
    const move = (ev) => {
      const dx = (ev.clientX - sx) / cw;
      const dy = (ev.clientY - sy) / ch;
      const f = base;
      let nx = f.x, ny = f.y, nw = f.w, nh = f.h;
      switch (mode) {
        case "move": nx = f.x + dx; ny = f.y + dy; break;
        case "se": nw = f.w + dx; nh = nw / aspect; break;
        case "nw": nw = f.w - dx; nh = nw / aspect; ny = f.y + (f.h - nh); break;
        case "ne": nw = f.w + dx; nh = nw / aspect; ny = f.y + (f.h - nh); break;
        case "sw": nw = f.w - dx; nh = nw / aspect; break;
        case "e": nw = f.w + dx; nh = nw / aspect; break;
        case "w": nw = f.w - dx; nh = nw / aspect; nx = f.x + (f.w - nw); break;
        case "s": nh = f.h + dy; nw = nh * aspect; break;
        case "n": nh = f.h - dy; nw = nh * aspect; ny = f.y + (f.h - nh); break;
        default: return;
      }
      const minW = 0.06;
      if (nw < minW) nw = minW;
      nh = nw / aspect;
      if (mode === "move") {
        nx = clamp(nx, -0.05, 1.05 - nw);
        ny = clamp(ny, -0.05, 1.05 - nh);
      } else {
        if (nx < -0.05) nx = -0.05;
        if (ny < -0.05) ny = -0.05;
        if (nx + nw > 1.05) nx = 1.05 - nw;
        if (ny + nh > 1.05) ny = 1.05 - nh;
      }
      setFrame({ x: nx, y: ny, w: nw, h: nh });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  if (!frame) {
    return (
      <div className="absolute top-[100px] right-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200" style={{ width: panelWidth }}>
        <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100">
          <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Print Layout</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700"><X className="w-4 h-4" /></button>
        </div>
      </div>
    );
  }

  const compact = panelWidth < 320;

  return (
    <Fragment>
      {/* Resizable print frame over the live map */}
      <div
        className="absolute z-[7] pointer-events-none"
        style={{
          left: `${frame.x * 100}%`,
          top: `${frame.y * 100}%`,
          width: `${frame.w * 100}%`,
          height: `${frame.h * 100}%`,
          boxShadow: "0 0 0 9999px rgba(15,23,42,0.22)",
        }}
      >
        <div className="absolute -top-[34px] left-0 flex items-center gap-1 pointer-events-auto bg-white border border-gray-300 rounded-md shadow-md px-1.5 py-1 cursor-move select-none" onPointerDown={(e) => startResize(e, "move")} title="Drag to move the print frame">
          <Move className="w-3 h-3 text-blue-600" />
          <span className="text-[10px] font-semibold text-gray-600">Move</span>
        </div>
        <div className="absolute inset-0 border-2 border-dashed border-blue-500 rounded-sm pointer-events-none" />
        <div className="absolute inset-0 pointer-events-none">
          {HANDLES.map((h) => (
            <div
              key={h.k}
              onPointerDown={(e) => startResize(e, h.k)}
              className={"absolute w-[11px] h-[11px] pointer-events-auto bg-white border-2 border-blue-600 rounded-[2px] " + h.cls + " " + h.curs}
              title={"Resize"}
            />
          ))}
        </div>
      </div>

      {/* Print Layout panel */}
      <div
        className="absolute top-[100px] right-[50px] z-20 bg-white rounded-lg shadow-xl border border-gray-200 flex flex-col overflow-hidden"
        style={{ width: panelWidth, maxHeight: "calc(100vh - 185px)" }}
      >
        <ResizeHandle width={panelWidth} min={300} max={560} onWidth={onPanelWidth} />
        <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100">
          <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Print Layout</h3>
          <div className="flex items-center gap-1">
            <button onClick={saveTemplate} title="Save template" className="p-1 text-gray-400 hover:text-gray-700"><Save className="w-4 h-4" /></button>
            <button onClick={resetTemplate} title="Reset to defaults" className="p-1 text-gray-400 hover:text-gray-700"><Undo2 className="w-4 h-4" /></button>
            <button onClick={onClose} title="Close" className="text-gray-400 hover:text-gray-700 ml-1"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="p-2.5 space-y-2 overflow-y-auto flex-1 min-h-0">
          {/* Page setup */}
          <Section title="Page Setup" icon={<FolderOpen className="w-3.5 h-3.5" />} open={sections.page} onToggle={() => setSections({ ...sections, page: !sections.page })}>
            <div className="grid grid-cols-2 gap-1">
              {Object.keys(TEMPLATES).map((k) => (
                <button
                  key={k}
                  onClick={() => setTemplate(k)}
                  className={"px-2 py-1.5 rounded text-[11px] font-semibold transition " + (cfg.template === k ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200")}
                >
                  {TEMPLATES[k].label}
                </button>
              ))}
            </div>
            {cfg.template === "custom" && (
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] font-semibold text-gray-500">Width (mm)
                  <input type="number" min="40" max="2200" value={cfg.customWmm} onChange={(e) => setCustom("customWmm", e.target.value)} className="w-full border border-gray-300 rounded px-2 py-1 text-xs mt-0.5" />
                </label>
                <label className="text-[11px] font-semibold text-gray-500">Height (mm)
                  <input type="number" min="40" max="2200" value={cfg.customHmm} onChange={(e) => setCustom("customHmm", e.target.value)} className="w-full border border-gray-300 rounded px-2 py-1 text-xs mt-0.5" />
                </label>
              </div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-gray-500">{page.wmm}×{page.hmm} mm</span>
              <div className="flex gap-1">
                {DPIS.map((d) => (
                  <button key={d} onClick={() => setCfg((p) => ({ ...p, dpi: d }))} className={"px-2 py-1 rounded text-[10px] font-bold " + (cfg.dpi === d ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200")}>{d} dpi</button>
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => fitFrame()} className="flex-1 px-2 py-1.5 rounded text-[11px] font-semibold bg-white border border-blue-300 text-blue-600 hover:bg-blue-50">Fit view</button>
              <button onClick={() => recomputeForTemplate(page.wmm, page.hmm)} className="flex-1 px-2 py-1.5 rounded text-[11px] font-semibold bg-white border border-gray-300 text-gray-600 hover:bg-gray-100">Center frame</button>
            </div>
          </Section>

          {/* Map elements */}
          <Section title="Map Elements" icon={<MapPin className="w-3.5 h-3.5" />} open={sections.elements} onToggle={() => setSections({ ...sections, elements: !sections.elements })}>
            <div className="grid grid-cols-2 gap-x-2">
              <CheckRow checked={cfg.showTitle} onChange={(v) => setCfg((p) => ({ ...p, showTitle: v }))} label="Title" />
              <CheckRow checked={cfg.legendOn} onChange={(v) => setCfg((p) => ({ ...p, legendOn: v }))} label="Legend" />
              <CheckRow checked={cfg.scaleBarOn} onChange={(v) => setCfg((p) => ({ ...p, scaleBarOn: v }))} label="Scale bar" />
              <CheckRow checked={cfg.northOn} onChange={(v) => setCfg((p) => ({ ...p, northOn: v }))} label="North arrow" />
              <CheckRow checked={cfg.gridOn} onChange={(v) => setCfg((p) => ({ ...p, gridOn: v }))} label="Grid coords" />
              <CheckRow checked={cfg.locatorOn} onChange={(v) => setCfg((p) => ({ ...p, locatorOn: v }))} label="Locator inset" />
              <CheckRow checked={cfg.notesOn} onChange={(v) => setCfg((p) => ({ ...p, notesOn: v }))} label="Notes" />
              <CheckRow checked={!!cfg.logoData} onChange={(v) => { if (!v) setCfg((p) => ({ ...p, logoData: null })); }} label="Logo" />
            </div>

            {cfg.gridOn && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-gray-500">Style</span>
                  <select value={cfg.gridStyle} onChange={(e) => setCfg((p) => ({ ...p, gridStyle: e.target.value }))} className="border border-gray-300 rounded px-2 py-1 text-xs">
                    <option value="ticks">Tick marks only</option>
                    <option value="lines">Full grid lines</option>
                  </select>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-gray-500">Interval (deg)</span>
                  <input type="number" min="0.001" step="any" value={cfg.gridInterval || ""} placeholder="Auto"
                    onChange={(e) => setCfg((p) => ({ ...p, gridInterval: e.target.value === "" ? 0 : clamp(Number(e.target.value) || 0, 0.001, 360) }))}
                    className="w-24 border border-gray-300 rounded px-2 py-1 text-xs" />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-gray-500">Max per side</span>
                  <input type="number" min="2" max="20" value={cfg.gridMaxLabels}
                    onChange={(e) => setCfg((p) => ({ ...p, gridMaxLabels: clamp(Number(e.target.value) || 6, 2, 20) }))}
                    className="w-14 border border-gray-300 rounded px-2 py-1 text-xs" />
                </div>
                <p className="text-[10px] text-gray-400">Interval auto = clean round step targeting "Max per side" labels; override to force a fixed spacing.</p>
              </div>
            )}

            {cfg.showTitle && (
              <div className="space-y-1.5">
                <input type="text" value={cfg.title} onChange={(e) => setCfg((p) => ({ ...p, title: e.target.value }))} placeholder="Map title e.g. Land Parcels - Al Regoin" className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs" />
                <input type="text" value={cfg.subtitle} onChange={(e) => setCfg((p) => ({ ...p, subtitle: e.target.value }))} placeholder="Subtitle (optional)" className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs" />
              </div>
            )}

            {cfg.legendOn && (
              <div>
                <p className="text-[11px] font-semibold text-gray-500 mb-1">Layers in frame ({legendEntries.length})</p>
                {legendEntries.length ? (
                  <div className="max-h-32 overflow-y-auto border border-gray-200 rounded p-1.5 space-y-1">
                    {legendEntries.map((e) => (
                      <div key={e.table} className="flex items-center gap-2 text-xs">
                        <span className="w-3 h-3 rounded-full border border-gray-300 flex-shrink-0" style={{ backgroundColor: e.color }} />
                        <span className="text-gray-700 truncate">{e.label}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-[11px] text-gray-400">No layers with data in the print frame.</p>
                )}
                <p className="text-[10px] text-gray-400 mt-1">Only layers actually shown inside the frame are listed.</p>
              </div>
            )}

            {cfg.scaleBarOn && (
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold text-gray-500">Scale units</span>
                <select value={cfg.scaleUnit} onChange={(e) => setCfg((p) => ({ ...p, scaleUnit: e.target.value }))} className="border border-gray-300 rounded px-2 py-1 text-xs">
                  <option value="auto">Auto</option>
                  <option value="m">Meters (m)</option>
                  <option value="km">Kilometers (km)</option>
                  <option value="mi">Miles (mi)</option>
                </select>
              </div>
            )}

            {cfg.northOn && (
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold text-gray-500">Arrow style</span>
                <select value={cfg.northStyle} onChange={(e) => setCfg((p) => ({ ...p, northStyle: e.target.value }))} className="border border-gray-300 rounded px-2 py-1 text-xs">
                  <option value="simple">Simple</option>
                  <option value="full">Compass rose</option>
                </select>
              </div>
            )}

            {cfg.notesOn && (
              <textarea value={cfg.notesText} onChange={(e) => setCfg((p) => ({ ...p, notesText: e.target.value }))} rows="2" placeholder="Notes / footer text" className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs" />
            )}

            {cfg.logoData ? (
              <div className="flex items-center justify-between">
                <select value={cfg.logoPos} onChange={(e) => setCfg((p) => ({ ...p, logoPos: e.target.value }))} className="border border-gray-300 rounded px-2 py-1 text-xs">
                  <option value="br">Bottom-right</option>
                  <option value="bl">Bottom-left</option>
                  <option value="tr">Top-right</option>
                  <option value="tl">Top-left</option>
                </select>
                <button onClick={() => { logoImgRef.current = null; setCfg((p) => ({ ...p, logoData: null })); }} className="text-[11px] font-semibold text-red-600 hover:text-red-800 px-2">Remove</button>
              </div>
            ) : (
              <label className="flex items-center justify-center gap-2 border border-dashed border-gray-300 rounded px-2 py-2 text-xs text-gray-500 cursor-pointer hover:bg-gray-50">
                <Upload className="w-3.5 h-3.5" />
                Upload logo image
                <input type="file" accept="image/*" className="sr-only" onChange={(e) => {
                  const f = e.target.files && e.target.files[0];
                  if (!f) return;
                  const r = new FileReader();
                  r.onload = () => setCfg((p) => ({ ...p, logoData: r.result }));
                  r.readAsDataURL(f);
                  e.target.value = "";
                }} />
              </label>
            )}
          </Section>

          {/* Preview */}
          <Section title="Preview & Export" icon={<Grid3x3 className="w-3.5 h-3.5" />} open={sections.preview} onToggle={() => setSections({ ...sections, preview: !sections.preview })}>
            <div className="relative">
              {preview ? (
                <img src={preview} alt="Print preview" className="w-full rounded border border-gray-200" />
              ) : (
                <div className="flex items-center justify-center h-40 border border-gray-100 rounded text-[11px] text-gray-400">
                  {busy === "preview" ? "Rendering preview..." : "Move the frame over the map to compose."}
                </div>
              )}
              {busy === "preview" && (
                <div className="absolute inset-0 bg-white/50 flex items-center justify-center rounded">
                  <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
                </div>
              )}
            </div>
            <button onClick={forceRefresh} className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-[11px] font-semibold bg-white border border-gray-300 text-gray-600 hover:bg-gray-100">
              <RefreshCw className="w-3.5 h-3.5" /> Refresh preview
            </button>
            <div className="grid grid-cols-3 gap-1">
              {[["png", "PNG", <ImageIcon key="i" className="w-3 h-3" />], ["jpeg", "JPEG", <ImageIcon key="j" className="w-3 h-3" />], ["pdf", "PDF", <FileDown key="p" className="w-3 h-3" />]].map(([f, label, icon]) => (
                <button key={f} onClick={() => doExport(f)} disabled={busy !== "idle"} className="flex items-center justify-center gap-1 px-2 py-2 rounded text-[11px] font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                  {busy === "exporting" ? <Loader2 className="w-3 h-3 animate-spin" /> : icon}
                  {busy === "exporting" ? "..." : label}
                </button>
              ))}
            </div>
            {warn && (
              <p className="flex items-start gap-1.5 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">
                <AlertTriangle className="w-3.5 h-3.5 mt-px flex-shrink-0" />
                <span>{warn}</span>
              </p>
            )}
            <p className="text-[10px] text-gray-400 leading-snug">
              Set the dashed frame over the map area to print. Export renders at full {cfg.dpi} dpi{scaleX ? " — map scale 1:" + scaleX.toLocaleString() : ""}.
            </p>
          </Section>
        </div>
      </div>
    </Fragment>
  );
}