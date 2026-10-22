import registry from "../../../../shared/ledger_fields.json";

const byKey = Object.fromEntries(registry.fields.map((f) => [f.key, f]));

function col(key) {
  const f = byKey[key];
  if (!f) throw new Error(`ledger field "${key}" is missing from shared/ledger_fields.json`);
  const out = { key: f.table_key || f.key, label: f.label };
  if (f.sort) out.sortKey = f.sort === true ? f.key : f.sort;
  if (f.align) out.align = f.align;
  if (f.mudryia_only) out.mudryiaOnly = true;
  if (f.always) out.always = true;
  return out;
}

export const ALL_COLS = registry.table_order.map(col);
export const DEFAULT_COLS = registry.default_columns;
