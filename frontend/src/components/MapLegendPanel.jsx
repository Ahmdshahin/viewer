import React, { useMemo, useState } from "react";
import { Layers2, ChevronDown, ArrowUp, ArrowDown } from "lucide-react";

/* One color swatch that mirrors the actual map rendering for each geometry type. */
function Swatch({ color, opacity, gtype }) {
  const c = color || "#3388ff";
  const o = opacity ?? 0.5;
  if (/POINT/.test(gtype || "")) {
    return <span className="w-3.5 h-3.5 rounded-full border border-black/20 flex-shrink-0" style={{ backgroundColor: c, opacity: o }} />;
  }
  if (/LINE/.test(gtype || "")) {
    return <span className="block w-5 h-[3px] rounded-full flex-shrink-0" style={{ backgroundColor: c, opacity: o }} />;
  }
  return <span className="block w-4 h-3 rounded-[2px] flex-shrink-0" style={{ backgroundColor: c, opacity: o, boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.25)" }} />;
}

export default function MapLegendPanel({
  layersCfg = [], layerOrder = [], layerStyle = {}, labelLayers = {},
  shownTables, expanded, onToggleExpanded, onMove,
}) {
  const ordered = useMemo(() => {
    const byOrder = [...layersCfg].sort((a, b) => layerOrder.indexOf(a.table) - layerOrder.indexOf(b.table));
    return byOrder;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layersCfg, layerOrder]);

  const shown = useMemo(() => {
    if (!Array.isArray(shownTables)) return null;
    return ordered.filter((l) => shownTables.includes(l.table));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ordered, shownTables]);

  const [openRows, setOpenRows] = useState(() => new Set());
  const toggleRow = (t) =>
    setOpenRows((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });

  return (
    <div className="absolute bottom-14 right-[10px] z-20 flex flex-col items-end">
      {/* Tool-style icon button - the only explicit expand/collapse control. */}
      <button
        onClick={onToggleExpanded}
        title="Legend"
        aria-expanded={expanded}
        className={"w-[35px] h-[35px] flex items-center justify-center bg-white rounded shadow-[0_0_0_2px_rgba(0,0,0,0.1)] " + (expanded ? "bg-amber-100 text-amber-700" : "text-gray-700 hover:bg-gray-100")}
      >
        <Layers2 className="w-[18px] h-[18px]" />
      </button>

      {expanded && (
        <div className="absolute bottom-0 right-[39px] w-64 max-w-[calc(100vw-24px)] bg-white rounded-lg shadow-xl border border-gray-200 overflow-hidden">
          <div className="px-2.5 py-1.5 text-[11px] font-bold text-gray-500 uppercase tracking-wider border-b border-gray-100 flex items-center gap-1.5 bg-white">
            <Layers2 className="w-3.5 h-3.5 text-amber-600" />
            Legend
            <span className="normal-case text-[10px] font-medium text-gray-400">({shown ? shown.length : "…"}/{ordered.length})</span>
          </div>

          <div className="max-h-[40vh] overflow-y-auto divide-y divide-gray-50">
            {shown === null && (
              <p className="px-3 py-3 text-[11px] text-gray-400">Updating legend…</p>
            )}
            {shown !== null && shown.length === 0 && (
              <p className="px-3 py-3 text-[11px] text-gray-400">No layers with data in the current view.</p>
            )}

            {(shown || []).map((l) => {
              const t = l.table;
              const style = layerStyle[t] || {};
              const rowOpen = openRows.has(t);
              const gtypeName = /POINT/.test(l.gtype || "") ? "Point" : /LINE/.test(l.gtype || "") ? "Line" : "Polygon";
              const opacityPct = Math.round((typeof style.opacity === "number" ? style.opacity : 0.5) * 100);
              return (
                <div key={t}>
                  <div className="flex items-center gap-1.5 px-2 py-1.5">
                    <button onClick={() => toggleRow(t)} title={rowOpen ? "Collapse" : "Expand"} className="text-gray-400 hover:text-gray-700 flex-shrink-0">
                      <ChevronDown className={"w-3.5 h-3.5 transition-transform " + (rowOpen ? "rotate-180" : "")} />
                    </button>
                    <Swatch color={style.color} opacity={style.opacity} gtype={l.gtype} />
                    <span className="flex-1 min-w-0 truncate text-xs text-gray-800">
                      {l.label || t}
                    </span>
                  </div>

                  {rowOpen && (
                    <div className="px-2.5 pb-2 pt-0.5 pl-[38px] space-y-1">
                      <div className="grid grid-cols-2 gap-x-2 text-[10px] text-gray-500">
                        <span>Geometry: <b className="text-gray-700">{gtypeName}</b></span>
                        <span>Opacity: <b className="text-gray-700">{opacityPct}%</b></span>
                        <span>Color: <b className="font-mono text-gray-700">{style.color || "#3388ff"}</b></span>
                        <span>Labels: <b className="text-gray-700">{labelLayers[t] ? "On" : "Off"}</b></span>
                      </div>
                      <div className="flex items-center gap-1 pt-0.5">
                        <button
                          disabled={!onMove || shown.indexOf(l) === 0}
                          onClick={() => onMove && onMove(t, -1)}
                          title="Move up"
                          className="p-0.5 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-100 disabled:opacity-30"
                        >
                          <ArrowUp className="w-3 h-3" />
                        </button>
                        <button
                          disabled={!onMove || shown.indexOf(l) === shown.length - 1}
                          onClick={() => onMove && onMove(t, 1)}
                          title="Move down"
                          className="p-0.5 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-100 disabled:opacity-30"
                        >
                          <ArrowDown className="w-3 h-3" />
                        </button>
                        <span className="text-[10px] text-gray-400 ml-1">Reorder</span>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}