"""Single source of truth for the ledger fields, shared with the frontend.

``shared/ledger_fields.json`` at the repo root defines every ledger field once
(key, Arabic table label, Excel header, display kind, sortability, ...). The
frontend table columns and this module's export/import schema are derived
from it, so a field is added (or renamed) in one place instead of five.
"""

import json
from pathlib import Path

_REGISTRY_PATH = Path(__file__).resolve().parents[3] / "shared" / "ledger_fields.json"

with _REGISTRY_PATH.open(encoding="utf-8") as _fh:
    REGISTRY = json.load(_fh)

FIELDS = REGISTRY["fields"]
BY_KEY = {f["key"]: f for f in FIELDS}

# (header, field key) in export order — headers are exactly what HEADER_MAP
# recognises, so an exported file re-imports through the intake tool.
EXPORT_COLUMNS = tuple((BY_KEY[key]["header"], key) for key in REGISTRY["export_order"])
EXPORT_KEYS = [key for _, key in EXPORT_COLUMNS]

# How the Excel writer formats a cell, driven by each field's "kind".
TEXT_KEYS = tuple(k for k, f in BY_KEY.items() if f.get("kind") == "text")
NUM_KEYS = tuple(k for k, f in BY_KEY.items() if f.get("kind") == "number")
COMMENT_KEYS = tuple(k for k, f in BY_KEY.items() if f.get("kind") == "comment")
STATUS_KEYS = tuple(k for k, f in BY_KEY.items() if f.get("kind") == "status")
