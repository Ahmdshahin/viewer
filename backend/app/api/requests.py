"""Requests ledger (طلبات التقنين) endpoints.

Primary business key is Req_Number (رقم الطلب); رقم التقنين (reqra_number) is
only an optional attribute of the request. Existing cadastral geometry tables
(land / eshghalat / point) are read-only here — they are linked by Req_Number.
"""

import csv
import io
import json
import math
import re
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session
from typing import List, Optional

from app.api import deps
from app.db.models import (
    AreaUnit, CadastralRequest, Center, Governorate, Notification,
    CANONICAL_SURVEY_STATUSES, REQUEST_STATUSES, SURVEY_STATUS_ALIASES,
    UNIT_TYPE_ALIASES, User, Village, AuditTrail,
)

router = APIRouter()

GEOM_TABLES = ("lands", "eshghalat", "points")

# Arabic sheet headers -> field keys (headers are stripped of whitespace).
HEADER_MAP = {
    "رقم الطلب": "req_number",
    "العنوان": "address",
    "المساحة": "area_value",
    "نوع المساحة": "area_unit_name",
    "توع الوحده": "unit_type",
    "الهاتف": "phone",
    "مقدم الطلب": "applicant",
    "رقم التقنين": "reqra_number",
    "المحافظة": "governorate",
    "المركز": "center",
    "القرية": "village",
    "الشركة": "company",
    "المساح": "surveyor",
    "حالة الرفع المساحي": "survey_status",
    "تعليق المكتب الفنى": "office_comment",
    "الحالة الطلب": "request_status",
    "المكتب الفنى": "office",
    "تاريخ الادخال": "entry_date",
    # Legacy intake exports (docs/1.csv..3.csv) carry columns the shared
    # template does not, but the ledgers have a place for them now.
    "علامات مميزة": "landmarks",
    "الفريق الميدانى": "field_team",
    "تاريخ التوزيع": "distribution_date",
    "تاريخ الارسال جيوديسيا": "geodesy_date",
    "تاريخ الارسال للمديريه": "directorate_date",
    "ملفات Raw": "raw_files",
    # 8888.csv: a second survey-upload date spelled with ى instead of ي. Exact
    # match wins over the loose fold, so it keeps its own field instead of
    # colliding with survey_date (the two carry different dates in 96% of rows).
    "تاريخ الرفع المساحى": "alt_survey_date",
    # 8888.csv source-system shapefile flag.
    "BaseMap": "base_map",
}
RESULT_HEADER_MAP = {
    "رقم الطلب": "req_number",
    "النتيجة": "result",
    "الحالة": "result",
    "القبول والرفض": "result",
    "رقم التقنين": "reqra_number",
}

# Spellings seen in hand-made sheets that should mean the same field as the
# canonical name above. Kept separate from HEADER_MAP so the template we hand
# out still prints the canonical names, while real files import cleanly.
HEADER_ALIASES = {
    # applicant
    "اسم مقدم الطلب": "applicant",
    "صاحب الطلب": "applicant",
    # area unit (the unit, not the number — the number is in المساحة)
    "وحدة المساحة": "area_unit_name",
    "وحده القياس": "area_unit_name",
    # unit type
    "نوع الوحده": "unit_type",
    "نوع الوحدة": "unit_type",
    # office / surveyor
    "المكتب الفني": "office",
    "تعليق المكتب الفني": "office_comment",
    # status wording variants
    "الحاله الطلب": "request_status",
    "حالة الطلب": "request_status",
    "حاله الطلب": "request_status",
    "الحالة": "request_status",
    "حالة الرفع المساحى": "survey_status",
    "حالة الرفع": "survey_status",
    # date
    "تاريخ الدخول": "entry_date",
    "تاريخ الطلب": "entry_date",
    "تاريخ الادخال ": "entry_date",
    # plain text / phone
    "العنوان بالتفصيل": "address",
    "رقم الهاتف": "phone",
    "الجوال": "phone",
    "تليفون": "phone",
    "رقم التلفون": "phone",
    # req number
    "رقم طلب ": "req_number",
    "رقم الطلب ": "req_number",
    "رقم": "req_number",
    # survey / village / center
    "اسم المساح": "surveyor",
    "اسم القرية": "village",
    "اسم المركز": "center",
    "اسم المحافظة": "governorate",
    # reqra
    "رقم التقنين ": "reqra_number",
    "التقنين": "reqra_number",
    # company
    "اسم الشركة": "company",
    # survey date — the intake sheet spells it two ways, both mean the same date
    "تاريخ الرفع المساحي": "survey_date",
    "تاريخ الرفع": "survey_date",
    "تاريخ الرفغ المساحي": "survey_date",
    "تاريخ المعاينة": "survey_date",
    "تاريخ المعاينه": "survey_date",
    # Legacy intake exports (docs/1.csv..3.csv) name existing fields differently
    "الاسم": "applicant",
    "الشياخة / القرية": "village",
    "القسم / المركز": "center",
    "رقم التليفون": "phone",
    "تعليق المكتب الفنى ميداني": "survey_comment",
    # Singular spelling of the landmark column (the template prints the plural
    # علامات مميزة, hand-made sheets often drop the ة-ت plural).
    "علامة مميزة": "landmarks",
    # The status sheet of the company workbook spells the same two columns
    # without the leading ال.
    "مساح": "surveyor",
    "مكتب فنى": "office",
}

AREA_UNIT_ALIASES = {
    "متر مربع": "sqm", "م²": "sqm", "م2": "sqm", "sqm": "sqm",
    "قيراط": "kirat", "ق": "kirat", "kirat": "kirat",
    "سهم": "share", "س": "share", "share": "share",
    "فدان": "feddan", "ف": "feddan", "feddan": "feddan",
}

_AR_DIGITS = dict(zip([ord(c) for c in "٠١٢٣٤٥٦٧٨٩"], "0123456789"))
_PE_DIGITS = dict(zip([ord(c) for c in "۰۱۲۳۴۵۶۷۸۹"], "0123456789"))


def _norm_key(s: str) -> str:
    return "".join(s.split()).strip()


def _norm_headers(header_map: dict) -> dict:
    return {_norm_key(k): v for k, v in header_map.items()}


# Arabic is routinely typed with different (all valid) spellings of the same
# letter, and sheets add punctuation, tatweel and diacritics. Fold those away so
# a header only has to be *recognisably* the right column, not byte-identical.
_AR_FOLD = str.maketrans({
    "\u0623": "\u0627", "\u0625": "\u0627", "\u0622": "\u0627",  # أ إ آ -> ا
    "\u0671": "\u0627",                                          # ٱ -> ا
    "\u0649": "\u064a",                                          # ى -> ي
    "\u0629": "\u0647",                                          # ة -> ه
    "\u0624": "\u0648",                                          # ؤ -> و
    "\u0626": "\u064a",                                          # ئ -> ي
})
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def _loose_key(s: str) -> str:
    """Normalise a header for tolerant matching (case/punctuation/letter shape)."""
    return _NON_WORD.sub("", str(s or "")).translate(_AR_FOLD).lower()


_ALL_HEADERS = {**HEADER_MAP, **HEADER_ALIASES}
_HEADER_LOOKUP = _norm_headers(HEADER_MAP)
_RESULT_LOOKUP = _norm_headers(RESULT_HEADER_MAP)
_HEADER_LOOSE = {_loose_key(k): v for k, v in _ALL_HEADERS.items()}
_RESULT_LOOSE = {_loose_key(k): v for k, v in RESULT_HEADER_MAP.items()}
# Strict match over the intake map *including* aliases.
_HEADER_ALL_LOOKUP = _norm_headers(_ALL_HEADERS)


def _resolve_field(header: str, kind: str = "intake"):
    """Map a sheet header to a field, exact match first, then tolerant match.

    ``kind`` disambiguates headers that exist in both maps. "الحالة" is the
    verdict in a results sheet but the request status in an intake sheet, so the
    intake map is consulted first for an intake import and the results map first
    for a results import.

    Returns None for a column we have no meaning for, so the caller can report it
    as unmapped instead of silently dropping it.
    """
    if kind == "result":
        for table in (_RESULT_LOOKUP, _HEADER_ALL_LOOKUP):
            if header in table:
                return table[header]
        loose_key = _loose_key(header)
        for table in (_RESULT_LOOSE, _HEADER_LOOSE):
            if loose_key in table:
                return table[loose_key]
        return None

    for table in (_HEADER_ALL_LOOKUP, _RESULT_LOOKUP):
        if header in table:
            return table[header]
    loose_key = _loose_key(header)
    for table in (_HEADER_LOOSE, _RESULT_LOOSE):
        if loose_key in table:
            return table[loose_key]
    return None


def _to_ascii_digits(value) -> str:
    return str(value or "").translate(_AR_DIGITS).translate(_PE_DIGITS)


def _parse_number(value) -> Optional[float]:
    if value is None:
        return None
    s = _to_ascii_digits(value).replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    # "100 م" / "156 متر مربع" — a number typed with its (Arabic) unit in the
    # same cell. Only an all-Arabic-letter suffix counts, so a misplaced date
    # like "5/4/2026" is still rejected instead of silently read as 5.
    m = re.match(r"^(\d+(?:\.\d+)?)\s*[\u0600-\u06FF\s]+$", s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _parse_date(value) -> Optional[date]:
    if value is None:
        return None
    s = _to_ascii_digits(value).strip()
    if not s:
        return None
    # ISO 8601 timestamps (2026-02-03T22:00:00Z) — the legacy exports store
    # these for the distribution / survey dates. Python 3.10 cannot parse the
    # trailing Z, so normalise it to an offset first.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00")).date()
    except ValueError:
        pass
    # Source sheets use US-style %m/%d/%Y for slash dates.
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Excel stores dates as day numbers (46072 = 2026-03-19). Accept only a
    # plausible serial, so an id or a phone number can never become a date.
    try:
        n = float(s)
    except ValueError:
        return None
    if 1 <= n <= 2958465:  # 1900-01-01 .. 9999-12-31
        return (datetime(1899, 12, 30) + timedelta(days=n)).date()
    return None


# Fields that hold dates. When a sheet repeats one field in two columns (the
# intake template does, and the legacy exports do), whichever column actually
# parses as a date wins over an unreadable one.
_DATE_FIELDS = frozenset({
    "entry_date", "survey_date", "alt_survey_date", "distribution_date",
    "geodesy_date", "directorate_date",
})


# Field groups a usable intake sheet is expected to supply. Each entry is
# (label, acceptable header-matched field names). `req_number` is the key and is
# checked separately; the rest are what make a row meaningful.
_REQUIRED_GROUPS = (
    ("applicant", ("applicant",)),
    ("location (governorate/center/village)", ("governorate", "center", "village")),
    ("area", ("area_value",)),
    ("request status", ("request_status",)),
    ("entry date", ("entry_date",)),
)


def _sheet_coverage(parsed: List[dict]) -> tuple:
    """Describe how much of the sheet actually mapped.

    Returns (rows_with_number, recognised_field_names, average_fields_per_row,
    missing_required_group_labels).
    """
    seen = set()
    rows_with_no = 0
    total_fields = 0
    for row in parsed:
        filled = [k for k, v in row.items() if v not in (None, "")]
        total_fields += len(filled)
        seen.update(filled)
        if row.get("req_number"):
            rows_with_no += 1
    avg = (total_fields / len(parsed)) if parsed else 0.0
    missing = [label for label, names in _REQUIRED_GROUPS if not (seen & set(names))]
    return rows_with_no, seen, avg, missing


_EXPECTED_HEADERS = (
    "\u0631\u0642\u0645 \u0627\u0644\u0637\u0644\u0628 | \u0645\u0642\u062f\u0645 \u0627\u0644\u0637\u0644\u0628 | "
    "\u0627\u0644\u0647\u0627\u062a\u0641 | \u0627\u0644\u0639\u0646\u0648\u0627\u0646 | \u0627\u0644\u0645\u0633\u0627\u062d\u0629 | "
    "\u0646\u0648\u0639 \u0627\u0644\u0645\u0633\u0627\u062d\u0629 | \u0646\u0648\u0639 \u0627\u0644\u0648\u062d\u062f\u0629 | \u0627\u0644\u0634\u0631\u0643\u0629 | "
    "\u0627\u0644\u0645\u062d\u0627\u0641\u0638\u0629 | \u0627\u0644\u0645\u0631\u0643\u0632 | \u0627\u0644\u0642\u0631\u064a\u0629 | "
    "\u0627\u0644\u0645\u0633\u0627\u062d | \u0627\u0644\u0645\u0643\u062a\u0628 \u0627\u0644\u0641\u0646\u064a | "
    "\u062d\u0627\u0644\u0629 \u0627\u0644\u0631\u0641\u0639 \u0627\u0644\u0645\u0633\u0627\u062d\u064a | "
    "\u062a\u0639\u0644\u064a\u0642 \u0627\u0644\u0645\u0643\u062a\u0628 \u0627\u0644\u0641\u0646\u064a | "
    "\u0627\u0644\u062d\u0627\u0644\u0629 \u0627\u0644\u0637\u0644\u0628 | \u0631\u0642\u0645 \u0627\u0644\u062a\u0642\u0646\u064a\u0646 | "
    "\u062a\u0627\u0631\u064a\u062e \u0627\u0644\u0627\u062f\u062e\u0627\u0644"
)


def _reject_unmapped_sheet(parsed, unmapped):
    """Refuse an import whose headers clearly did not match the mapping.

    The failure this guards against is silent: a sheet whose headers differ from
    the expected ones still yields a req_number column, so rows get inserted --
    but with no applicant, no location, no area and no real entry date.
    """
    rows_with_no, seen, avg, missing = _sheet_coverage(parsed)
    if not rows_with_no or "req_number" not in seen:
        return
    # Refuse only when the sheet is missing most of what makes a record useful.
    # A genuinely sparse sheet still gets through, and force= always overrides.
    if len(missing) >= 3:
        raise HTTPException(
            status_code=400,
            detail=(
                "\u062a\u0645 \u0625\u064a\u0642\u0627\u0641 \u0627\u0644\u0627\u0633\u062a\u064a\u0631\u0627\u062f: "
                "\u0631\u0624\u0648\u0633 \u0627\u0644\u0623\u0639\u0645\u062f\u0629 \u0641\u064a \u0627\u0644\u0645\u0644\u0641 "
                "\u0644\u0627 \u062a\u0637\u0628\u0642 \u0627\u0644\u0623\u0633\u0645\u0627\u0621 \u0627\u0644\u0645\u062a\u0648\u0642\u0639\u0629. "
                f"\u0645\u0646 {rows_with_no} \u0635\u0641\u060c \u062a\u0645 \u0627\u0644\u062a\u0639\u0631\u0641 \u0639\u0644\u0649 {len(seen)} "
                f"\u0639\u0645\u0648\u062f \u0641\u0642\u0637 (\u0628\u0645\u0639\u062f\u0644 {avg:.1f} \u0642\u064a\u0645\u0629 \u0644\u0643\u0644 \u0635\u0641). "
                "\u0627\u0644\u062d\u0642\u0648\u0642 \u0627\u0644\u062a\u0627\u0644\u064a\u0629 \u0645\u0641\u0642\u0648\u062f\u0629 \u0645\u0646 \u0627\u0644\u0645\u0644\u0641: "
                + "\u060c ".join(missing) + ". "
                "\u0627\u0644\u0627\u0633\u062a\u064a\u0631\u0627\u062f \u0633\u064a\u0645\u0644\u0623 \u0627\u0644\u0633\u062c\u0644 \u0628\u0637\u0644\u0628\u0627\u062a "
                "\u0628\u0644\u0627 \u0645\u0642\u062f\u0645 \u0637\u0644\u0628 \u0648\u0644\u0627 \u0645\u0648\u0642\u0639 \u0648\u0644\u0627 \u0645\u0633\u0627\u062d\u0629 \u0648\u0644\u0627 \u062a\u0627\u0631\u064a\u062e. "
                f"\u0627\u0644\u0623\u0639\u0645\u062f\u0629 \u063a\u064a\u0631 \u0627\u0644\u0645\u0639\u0631\u0641\u0629: "
                f"{', '.join(sorted(unmapped)) or '(none)'} \u2014 "
                f"\u0627\u0644\u0623\u0633\u0645\u0627\u0621 \u0627\u0644\u0645\u062a\u0648\u0642\u0639\u0629: {_EXPECTED_HEADERS}. "
                "\u0623\u0639\u062f \u062a\u0633\u0645\u064a\u0629 \u0631\u0624\u0648\u0633 \u0627\u0644\u0623\u0639\u0645\u062f\u0629 \u062b\u0645 \u0623\u0639\u062f "
                "\u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629\u060c \u0623\u0648 \u0623\u0636\u0641 force=true \u0644\u0644\u062a\u062c\u0627\u0648\u0632."
            ),
        )

def parse_sheet(raw: bytes, filename: str, unmapped_out: Optional[set] = None,
                kind: str = "intake") -> List[dict]:
    """Parse an .xlsx or .csv upload into a list of field->value dicts.

    When ``unmapped_out`` is a set, every column header that is not recognised
    is added to it, so an import can tell the user which of their sheet's
    columns were ignored instead of silently dropping data.

    ``kind`` is "intake" for new requests or "result" for survey results; it
    decides how headers that appear in both maps are read.
    """
    rows: List[list] = []
    header: List[str] = []
    if filename.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            # Every sheet, not just the active one: the real intake workbooks
            # are multi-sheet (a summary sheet plus per-governorate sheets, or
            # a status sheet plus the data sheet) and the data usually lives
            # on a non-active sheet. Rows sharing a request number are merged
            # by the fill-in-place import anyway, so extra sheets can only add
            # the fields the first one was missing. A sheet without a request
            # number column is a report or reference tab — reading it would
            # only add its bookkeeping headers to the unmapped report.
            for ws in wb.worksheets:
                it = ws.iter_rows(values_only=True)
                sheet_header = [_norm_key(str(c)) if c is not None else "" for c in next(it, [])]
                if not any(_resolve_field(h, kind) == "req_number" for h in sheet_header if h):
                    continue
                if not header:
                    header = sheet_header
                else:
                    header.extend(h for h in sheet_header if h not in header)
                for r in it:
                    if r is None or all(c in (None, "") for c in r):
                        continue
                    # Keep header/value as pairs, not a dict: a sheet may repeat a
                    # column name and a dict would silently drop all but the last.
                    rows.append(list(zip(sheet_header, r)))
        finally:
            wb.close()
    else:
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp1256", "windows-1256", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            raise HTTPException(status_code=400, detail="Unreadable file encoding")
        reader = csv.reader(io.StringIO(text))
        try:
            header = [_norm_key(h) for h in next(reader)]
        except StopIteration:
            header = []
        for r in reader:
            if not r or all(not (v or "").strip() for v in r):
                continue
            rows.append(list(zip(header, r)))

    if unmapped_out is not None:
        unmapped_out.update(
            h for h in header
            if h and _resolve_field(h, kind) is None
        )

    mapped = []
    for row in rows:
        out = {}
        for k, v in row:
            field = _resolve_field(k, kind)
            if not field:
                continue
            # Two sheet columns can name the same field: the intake template
            # repeats "تعليق المكتب الفنى" and spells the survey date two ways.
            # A plain assignment would let the later, usually empty, duplicate
            # erase the value the user actually typed, so keep the first
            # non-empty value and let a later non-empty one fill a gap.
            if out.get(field) not in (None, ""):
                # A legacy export can hold an unreadable serial in the first
                # date column and a real date in the second, so a date field
                # also upgrades when only the later value parses.
                if (field in _DATE_FIELDS and v not in (None, "")
                        and _parse_date(v) is not None
                        and _parse_date(out[field]) is None):
                    out[field] = v
                continue
            if v in (None, ""):
                continue
            out[field] = v
        if out:
            mapped.append(out)
    return mapped


def _audit(db: Session, current_user: User, record_id: int, action: str, old: dict = None, new: dict = None,
           table_name: str = "requests"):
    db.add(AuditTrail(
        table_name=table_name,
        record_id=record_id,
        action=action,
        old_values=json.dumps(old, ensure_ascii=False) if old else None,
        new_values=json.dumps(new, ensure_ascii=False) if new else None,
        user_id=current_user.id,
        username=current_user.username,
    ))


def _record_created(created_out: Optional[dict], kind: str, name: str) -> None:
    """Remember a lookup value an import had to create, for the import report."""
    if created_out is None:
        return
    bucket = created_out.setdefault(kind, [])
    if name not in bucket:
        bucket.append(name)


def get_or_create_governorate(db: Session, name: str, code: Optional[str] = None,
                              created_out: Optional[dict] = None) -> Optional[int]:
    name = (name or "").strip()
    code = (code or "").strip() or None
    if not name:
        return None
    gov = None
    if code:
        gov = db.query(Governorate).filter(Governorate.code == code).first()
    if not gov:
        gov = db.query(Governorate).filter(Governorate.name == name).first()
    if not gov:
        # A legacy sheet may spell the same governorate slightly differently
        # (ى/ي, hamza, stray spaces); fold before creating a near-duplicate.
        key = _loose_key(name)
        for cand in db.query(Governorate).all():
            if _loose_key(cand.name) == key:
                gov = cand
                break
    if not gov:
        gov = Governorate(name=name, code=code)
        db.add(gov)
        db.flush()
        _record_created(created_out, "governorates", name)
    elif code and not gov.code:
        gov.code = code
    return gov.id if gov else None


def get_or_create_center(db: Session, governorate_id: Optional[int], name: str,
                         code: Optional[str] = None,
                         created_out: Optional[dict] = None) -> Optional[int]:
    name = (name or "").strip()
    # A legacy export often leaves the centre column empty while the request
    # number still carries its 4-digit code, so fall back to the code instead
    # of giving up (a missing centre would then leave the village homeless).
    if not name and code:
        center = db.query(Center).filter(Center.code == code).first()
        return center.id if center else None
    if not name:
        return None
    # centers.governorate_id is NOT NULL: without a governorate there is
    # nowhere to hang the centre, so skip rather than fail the whole row.
    if governorate_id is None:
        return None
    center = db.query(Center).filter(
        Center.governorate_id == governorate_id, Center.name == name
    ).first()
    if not center:
        key = _loose_key(name)
        for cand in db.query(Center).filter(Center.governorate_id == governorate_id).all():
            if _loose_key(cand.name) == key:
                center = cand
                break
    if not center:
        center = Center(governorate_id=governorate_id, name=name, code=code)
        db.add(center)
        db.flush()
        _record_created(created_out, "centers", name)
    elif code and not center.code:
        center.code = code
    return center.id if center else None


def get_or_create_village(db: Session, center_id: Optional[int], name: str,
                          created_out: Optional[dict] = None) -> Optional[int]:
    name = (name or "").strip()
    if not name:
        return None
    # villages.center_id is NOT NULL: without a centre there is nowhere to hang
    # the village, so skip rather than fail the whole row.
    if center_id is None:
        return None
    village = db.query(Village).filter(Village.center_id == center_id, Village.name == name).first()
    if not village:
        key = _loose_key(name)
        for cand in db.query(Village).filter(Village.center_id == center_id).all():
            if _loose_key(cand.name) == key:
                village = cand
                break
    if not village:
        village = Village(center_id=center_id, name=name)
        db.add(village)
        db.flush()
        _record_created(created_out, "villages", name)
    return village.id if village else None


def _resolve_area_unit(db: Session, name: str) -> Optional[int]:
    key = _norm_key(name or "")
    code = AREA_UNIT_ALIASES.get(key)
    if code is None:
        unit = db.query(AreaUnit).filter(AreaUnit.name == (name or "").strip()).first()
        return unit.id if unit else None
    unit = db.query(AreaUnit).filter(AreaUnit.code == code).first()
    return unit.id if unit else None


def _resolve_person(db: Session, name: str) -> Optional[int]:
    name = (name or "").strip()
    if not name:
        return None
    user = db.query(User).filter(
        or_(User.full_name == name, User.username == name)
    ).first()
    return user.id if user else None


def _assignee_name(db: Session, r) -> Optional[str]:
    """Username owning the request, or None when it is still unassigned."""
    uid = r.assigned_surveyor_id or r.assigned_office_id
    if not uid:
        return None
    user = db.query(User).filter(User.id == uid).first()
    return user.username if user else None


def _claim_if_unassigned(r, changes: dict, current_user: User) -> None:
    """An edit takes ownership of a request nobody is assigned to.

    Only called when something actually changed. An explicit surveyor/office
    pick (which resolves a user id above) or an existing assignment always
    wins, so this fires just for the "edited but still unowned" case and
    records the new owner in the same audit entry.
    """
    if r.assigned_surveyor_id is None and r.assigned_office_id is None:
        r.assigned_surveyor_id = current_user.id
        changes["assigned_to"] = current_user.username


def _parse_req_codes(req_number: str) -> tuple:
    """Extract (governorate_code, center_code) from e.g. A-Z26-2608-... or A-B2-0202-...

    Segment 2 is a letter designator followed by the numeric governorate code
    (Z26 -> 26, W23 -> 23, B2 -> 2); segment 3 is the 4-digit center code.
    """
    parts = (req_number or "").split("-")
    gov_code = None
    center_code = None
    if len(parts) >= 2:
        seg = parts[1].strip()
        m = re.match(r"^[A-Za-z]+(\d+)$", seg)
        if m:
            gov_code = m.group(1)
    for part in parts[2:]:
        p = part.strip()
        if p.isdigit() and len(p) >= 4:
            center_code = p
            break
    return gov_code, center_code


def _find_gov_by_code(db: Session, code: Optional[str]):
    if not code:
        return None
    return db.query(Governorate).filter(Governorate.code == code).first()


def _snap_status(value, canonical) -> Optional[str]:
    """Snap a status value from a sheet onto its canonical spelling.

    A sheet may write "تم المعاينه" where the lookup list says "تمت المعاينة".
    Storing the raw text would make the row invisible to the status filters, so
    fold the spelling and return the canonical form when they agree. An
    unrecognised value is returned as typed rather than dropped.
    """
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    for option in canonical:
        if text == option:
            return option
    folded = _loose_key(text)
    for option in canonical:
        if folded == _loose_key(option):
            return option
    return text


def _snap_survey_status(value) -> Optional[str]:
    """Canonical spelling for an incoming survey status.

    Whole-word phrasing variants ("إعادة المعاينة" vs the canonical
    "اعاده معاينه") survive the letter-shape fold, so the explicit alias map
    is consulted first (also folded, so spacing/hamza noise still hits);
    everything else snaps through the fold against the canonical list.
    """
    if isinstance(value, str):
        aliased = _SURVEY_STATUS_ALIAS_FOLDS.get(_loose_key(value))
        if aliased:
            return aliased
    return _snap_status(value, CANONICAL_SURVEY_STATUSES)


_SURVEY_STATUS_ALIAS_FOLDS = {_loose_key(k): v for k, v in SURVEY_STATUS_ALIASES.items()}


def _request_row_values(db: Session, row: dict, req_number: str, current_user: User,
                        created_out: Optional[dict] = None) -> dict:
    """Compute the column values one parsed intake row maps to.

    Shared by insert and update-in-place on both ledgers so both apply
    identical coercion and lookup resolution; lookups may create a missing
    governorate/center/village (recorded in ``created_out`` when given).
    """
    gov_code, center_code = _parse_req_codes(req_number)
    gov = _find_gov_by_code(db, gov_code)
    gov_id = gov.id if gov else get_or_create_governorate(db, row.get("governorate", ""), gov_code,
                                                          created_out=created_out)
    center_id = get_or_create_center(
        db, gov_id, str(row.get("center", "") or "").strip(), center_code or None,
        created_out=created_out)
    village_id = get_or_create_village(
        db, center_id, str(row.get("village", "") or "").strip(), created_out=created_out)
    surveyor = str(row.get("surveyor", "") or "").strip() or None
    office = str(row.get("office", "") or "").strip() or None
    unit_type = str(row.get("unit_type", "") or "").strip() or None
    if unit_type in UNIT_TYPE_ALIASES:
        unit_type = UNIT_TYPE_ALIASES[unit_type]
    return {
        "applicant": str(row.get("applicant", "") or "").strip() or None,
        "phone": str(row.get("phone", "") or "").strip() or None,
        "address": str(row.get("address", "") or "").strip() or None,
        "area_value": _parse_number(row.get("area_value")),
        "area_unit_id": _resolve_area_unit(db, row.get("area_unit_name", "")),
        "unit_type": unit_type,
        "company": str(row.get("company", "") or "").strip() or None,
        "governorate_id": gov_id,
        "center_id": center_id,
        "village_id": village_id,
        "surveyor_name": surveyor,
        "office_name": office,
        "assigned_surveyor_id": _resolve_person(db, surveyor),
        "assigned_office_id": _resolve_person(db, office),
        "survey_status": _snap_survey_status(row.get("survey_status")),
        "survey_comment": str(row.get("survey_comment", "") or "").strip() or None,
        "office_comment": str(row.get("office_comment", "") or "").strip() or None,
        "request_status": _snap_status(row.get("request_status"), REQUEST_STATUSES) or "جديد",
        "reqra_number": str(row.get("reqra_number", "") or "").strip() or None,
        # No default here: a fill must not invent an entry date the sheet did
        # not supply. The insert paths stamp date.today() when it is missing.
        "entry_date": _parse_date(row.get("entry_date")),
        "survey_date": _parse_date(row.get("survey_date")),
        # Columns the shared template lacks but the legacy exports carry.
        "landmarks": str(row.get("landmarks", "") or "").strip() or None,
        "field_team": str(row.get("field_team", "") or "").strip() or None,
        "distribution_date": _parse_date(row.get("distribution_date")),
        "geodesy_date": _parse_date(row.get("geodesy_date")),
        "directorate_date": _parse_date(row.get("directorate_date")),
        "raw_files": str(row.get("raw_files", "") or "").strip() or None,
        "alt_survey_date": _parse_date(row.get("alt_survey_date")),
        "base_map": str(row.get("base_map", "") or "").strip() or None,
        "status_updated_at": datetime.utcnow(),
        "imported_by_id": current_user.id,
        "created_by": current_user.username,
    }


def _fill_request_from_sheet_row(db: Session, record, row: dict,
                                 req_number: str, current_user: User,
                                 table_name: str = "requests",
                                 created_out: Optional[dict] = None) -> dict:
    """Fill the empty fields of an existing row from a re-imported sheet.

    A duplicate request number used to be skipped outright, which left rows
    imported before the sheet's headers were mapped with NULLs forever. Only
    fields the stored record does not have are touched — an existing status,
    address or date is never overwritten by a later import.
    """
    values = _request_row_values(db, row, req_number, current_user, created_out=created_out)
    changes = {}
    for field, new in values.items():
        if new is None:
            continue
        old = getattr(record, field, None)
        if old in (None, ""):
            setattr(record, field, new)
            changes[field] = new
    if changes:
        record.status_updated_at = datetime.utcnow()
        _audit(db, current_user, record.id, "IMPORT_UPDATE",
               old={}, new={k: str(v) for k, v in changes.items()},
               table_name=table_name)
    return changes


def _request_out(r: CadastralRequest, geom: dict = None, geom_count: int = None) -> dict:
    return {
        "id": r.id,
        "req_number": r.req_number,
        "applicant": r.applicant,
        "phone": r.phone,
        "address": r.address,
        "area_value": r.area_value,
        "area_unit": None,
        "unit_type": r.unit_type,
        "governorate": None,
        "center": None,
        "village": None,
        "surveyor": r.surveyor_name,
        "office": r.office_name,
        "survey_status": r.survey_status,
        "survey_comment": r.survey_comment,
        "office_comment": r.office_comment,
        "request_status": r.request_status or "جديد",
        "reqra_number": r.reqra_number,
        "entry_date": r.entry_date.isoformat() if r.entry_date else None,
        "survey_date": r.survey_date.isoformat() if r.survey_date else None,
        # Legacy intake columns — present on both ledgers.
        "landmarks": r.landmarks,
        "field_team": r.field_team,
        "distribution_date": r.distribution_date.isoformat() if r.distribution_date else None,
        "geodesy_date": r.geodesy_date.isoformat() if r.geodesy_date else None,
        "directorate_date": r.directorate_date.isoformat() if r.directorate_date else None,
        "raw_files": r.raw_files,
        "alt_survey_date": r.alt_survey_date.isoformat() if r.alt_survey_date else None,
        "base_map": r.base_map,
        "status_updated_at": r.status_updated_at.isoformat() if r.status_updated_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "created_by": r.created_by,
        "has_geometry": bool(geom) if geom is not None else None,
        "geometry_layers": geom or [],
        # One request may own many features (a boundary is a ring of points),
        # so report the number, not just whether any exist.
        "geometry_count": geom_count,
    }


def _attach_names(db: Session, item: dict, r: CadastralRequest) -> dict:
    if r.area_unit_id:
        unit = db.query(AreaUnit).filter(AreaUnit.id == r.area_unit_id).first()
        item["area_unit"] = unit.name if unit else None
    item["governorate"] = _resolve_name(db, "governorate", r.governorate_id)
    item["center"] = _resolve_name(db, "center", r.center_id)
    item["village"] = _resolve_name(db, "village", r.village_id)
    return item


def _resolve_name(db: Session, kind: str, value) -> Optional[str]:
    if not value:
        return None
    if kind == "governorate":
        row = db.query(Governorate).filter(Governorate.id == value).first()
        return row.name if row else None
    if kind == "center":
        row = db.query(Center).filter(Center.id == value).first()
        return row.name if row else None
    if kind == "village":
        row = db.query(Village).filter(Village.id == value).first()
        return row.name if row else None
    return None


def _bulk_geometry(db: Session, req_numbers: List[str], tables=GEOM_TABLES) -> dict:
    """Map each request number to the geometry layers it appears in.

    A request can own many features in one layer (a parcel boundary is a ring
    of points), so the count matters as much as the presence. Only the layer
    names are returned here, each once; use _bulk_geometry_counts for how many.
    """
    if not req_numbers:
        return {}
    result = {}
    for tbl in tables:
        try:
            rows = db.execute(
                text(f'SELECT DISTINCT "Req_Number" FROM {tbl} WHERE "Req_Number" = ANY(:vals)'),
                {"vals": list(req_numbers)},
            ).fetchall()
        except Exception:
            continue
        for (rn,) in rows:
            if tbl not in result.setdefault(rn, []):
                result[rn].append(tbl)
    return result


def _bulk_geometry_counts(db: Session, req_numbers: List[str], tables=GEOM_TABLES) -> dict:
    """Map each request number to how many geometry features it owns."""
    if not req_numbers:
        return {}
    result = {}
    for tbl in tables:
        try:
            rows = db.execute(
                text(f'SELECT "Req_Number", COUNT(*) FROM {tbl} '
                     f'WHERE "Req_Number" = ANY(:vals) GROUP BY 1'),
                {"vals": list(req_numbers)},
            ).fetchall()
        except Exception:
            continue
        for rn, n in rows:
            result[rn] = result.get(rn, 0) + int(n)
    return result


def _bulk_geometry_from_all(db: Session, tables=GEOM_TABLES) -> set:
    reqs = set()
    for tbl in tables:
        try:
            rows = db.execute(
                text(f'SELECT "Req_Number" FROM {tbl} WHERE "Req_Number" IS NOT NULL')
            ).fetchall()
            reqs.update(r[0] for r in rows)
        except Exception:
            continue
    return reqs


# Base_Map is derived from geometry, never typed by hand: the side form shows
# it read-only and every geometry write re-derives it through the helpers below.
BASEMAP_WITH_GEOM = "✔ shapefile"
BASEMAP_WITHOUT_GEOM = "Non_shapefile"


def sync_base_map_from_geometry(db: Session, req_number) -> None:
    """Re-derive Base_Map for a single request number on both ledgers."""
    sync_base_map_bulk(db, [req_number])


def sync_base_map_bulk(db: Session, req_numbers) -> None:
    """Set Base_Map to "✔ shapefile" for every given request that owns
    geometry features, and to "Non_shapefile" for every given request that
    owns none. Rows already holding the right flag are left untouched.

    Commits per chunk; callers treat a failure as non-fatal (the flag
    re-derives on the next geometry change).
    """
    # mudryia_requests imports this module, so the import stays lazy.
    from app.api.mudryia_requests import GEOM_TABLES as MUDRYIA_GEOM_TABLES
    reqs = [str(rn).strip() for rn in (req_numbers or []) if rn and str(rn).strip()]
    if not reqs:
        return
    for tbl, geom_tables in (("requests", GEOM_TABLES),
                             ("mudryia_requests", MUDRYIA_GEOM_TABLES)):
        for i in range(0, len(reqs), 2000):
            chunk = reqs[i:i + 2000]
            counts = _bulk_geometry_counts(db, chunk, geom_tables)
            rows = db.execute(
                text(f'SELECT "Req_Number", "Base_Map" FROM {tbl} '
                     f'WHERE "Req_Number" = ANY(:vals)'),
                {"vals": chunk},
            ).fetchall()
            updates = []
            for rn, cur in rows:
                want = BASEMAP_WITH_GEOM if counts.get(rn, 0) else BASEMAP_WITHOUT_GEOM
                if (cur or "").strip() != want:
                    updates.append({"rn": rn, "flag": want})
            if updates:
                db.execute(
                    text(f'UPDATE {tbl} SET "Base_Map" = :flag WHERE "Req_Number" = :rn'),
                    updates,
                )
                db.commit()


class RequestCreate(BaseModel):
    req_number: str
    applicant: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    area_value: Optional[float] = None
    area_unit: Optional[str] = None
    unit_type: Optional[str] = None
    governorate: Optional[str] = None
    center: Optional[str] = None
    village: Optional[str] = None
    surveyor: Optional[str] = None
    office: Optional[str] = None
    survey_status: Optional[str] = None
    survey_comment: Optional[str] = None
    office_comment: Optional[str] = None
    request_status: Optional[str] = None
    reqra_number: Optional[str] = None
    entry_date: Optional[str] = None
    survey_date: Optional[str] = None


class RequestUpdate(BaseModel):
    applicant: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    area_value: Optional[float] = None
    area_unit: Optional[str] = None
    unit_type: Optional[str] = None
    governorate: Optional[str] = None
    center: Optional[str] = None
    village: Optional[str] = None
    surveyor: Optional[str] = None
    office: Optional[str] = None
    survey_status: Optional[str] = None
    survey_comment: Optional[str] = None
    office_comment: Optional[str] = None
    request_status: Optional[str] = None
    reqra_number: Optional[str] = None
    entry_date: Optional[str] = None
    survey_date: Optional[str] = None
    distribution_date: Optional[str] = None
    alt_survey_date: Optional[str] = None
    geodesy_date: Optional[str] = None
    directorate_date: Optional[str] = None
    landmarks: Optional[str] = None
    field_team: Optional[str] = None
    raw_files: Optional[str] = None
    base_map: Optional[str] = None

    @field_validator("area_value", mode="before")
    @classmethod
    def _empty_area_to_none(cls, v):
        # The edit form sends "" when the number input is cleared; an omitted
        # key still means "leave as-is" (distinguished via model_fields_set).
        return None if v == "" else v


class TransitionIn(BaseModel):
    to: str
    comment: Optional[str] = None


class BulkAssignIn(BaseModel):
    ids: List[int]
    surveyor: Optional[str] = None
    office: Optional[str] = None


class BulkTransitionIn(BaseModel):
    ids: List[int]
    to: str
    comment: Optional[str] = None


ACCEPTED_SURVEY_STATUSES = ("تم المعاينة", "تمت المعاينة", "تم المعاينه")


def _require_staff(r):
    """Business rule: surveyor and office must both be chosen."""
    if not (r.surveyor_name or "").strip():
        raise HTTPException(status_code=400, detail="يجب اختيار المساح")
    if not (r.office_name or "").strip():
        raise HTTPException(status_code=400, detail="يجب اختيار المكتب الفني")


def _require_date_order(r):
    """Business rule: geodesy send date must not precede the field survey date."""
    if r.geodesy_date and r.alt_survey_date and r.geodesy_date < r.alt_survey_date:
        raise HTTPException(status_code=400, detail="تاريخ الارسال الجيوديسى يجب أن يكون بعد تاريخ الرفع الميدانى")


def _require_acceptable(r):
    """Business rule: a مقبول request must have a completed survey and a surveyor."""
    if (r.request_status or "").strip() != "مقبول":
        return
    if (r.survey_status or "").strip() not in ACCEPTED_SURVEY_STATUSES:
        raise HTTPException(status_code=400, detail="لا يمكن قبول الطلب قبل تم المعاينة")
    if not (r.surveyor_name or "").strip():
        raise HTTPException(status_code=400, detail="لا يمكن قبول الطلب بدون تحديد المساح")
    if not r.entry_date:
        raise HTTPException(status_code=400, detail="لا يمكن قبول الطلب بدون تاريخ الإدخال")


def _notify_user(db: Session, user_id: Optional[int], ntype: str, title: str,
                 body: str, link_req: Optional[str] = None):
    """Queue a single-user notification (assignee on assign/transition)."""
    if not user_id:
        return
    db.add(Notification(
        user_id=user_id,
        type=ntype,
        title=title,
        body=body,
        link_req=link_req,
    ))


def _apply_list_filters(query, db: Session, current_user: User, model, *,
                        q: Optional[str] = None,
                        governorate_id: Optional[int] = None,
                        center_id: Optional[int] = None,
                        village_id: Optional[int] = None,
                        request_status: Optional[str] = None,
                        survey_status: Optional[str] = None,
                        surveyor_id: Optional[int] = None,
                        office_id: Optional[int] = None,
                        assigned_to_me: bool = False,
                        has_geometry: Optional[bool] = None,
                        governorate: Optional[str] = None,
                        center: Optional[str] = None,
                        village: Optional[str] = None,
                        surveyor: Optional[str] = None,
                        office: Optional[str] = None,
                        entry_from: Optional[str] = None,
                        entry_to: Optional[str] = None,
                        survey_from: Optional[str] = None,
                        survey_to: Optional[str] = None,
                        sort: Optional[str] = None,
                        dir: Optional[str] = None,
                        ids: Optional[str] = None,
                        geom_tables=GEOM_TABLES):
    """Apply the ledger's list filters — shared by list and CSV export.

    Both ledgers filter identically (only the model and geometry tables
    differ), so one builder keeps the export exactly in step with the list.
    """
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            model.req_number.ilike(like),
            model.applicant.ilike(like),
            model.phone.ilike(like),
            model.address.ilike(like),
            model.company.ilike(like),
            model.reqra_number.ilike(like),
        ))
    if ids:
        id_list = [int(x) for x in str(ids).split(",") if x.strip().isdigit()]
        query = query.filter(model.id.in_(id_list)) if id_list else query.filter(text("1=0"))
    if governorate_id is not None:
        query = query.filter(model.governorate_id == governorate_id)
    if center_id is not None:
        query = query.filter(model.center_id == center_id)
    if village_id is not None:
        query = query.filter(model.village_id == village_id)
    if request_status:
        query = query.filter(model.request_status == request_status)
    if survey_status:
        query = query.filter(model.survey_status == survey_status)
    if surveyor_id is not None:
        query = query.filter(model.assigned_surveyor_id == surveyor_id)
    if office_id is not None:
        query = query.filter(model.assigned_office_id == office_id)
    if assigned_to_me:
        query = query.filter(or_(
            model.assigned_surveyor_id == current_user.id,
            model.assigned_office_id == current_user.id,
        ))
    if has_geometry is not None:
        geom_reqs = _bulk_geometry_from_all(db, geom_tables)
        if has_geometry:
            query = query.filter(model.req_number.in_(geom_reqs))
        else:
            all_reqs = [rn for (rn,) in db.query(model.req_number).all() if rn]
            query = query.filter(model.req_number.in_(
                [rn for rn in all_reqs if rn not in geom_reqs]))
    if governorate:
        gov_ids = [i for (i,) in db.query(Governorate.id)
                   .filter(Governorate.name.ilike(f"%{governorate.strip()}%")).all()]
        query = query.filter(model.governorate_id.in_(gov_ids)) if gov_ids else query.filter(text("1=0"))
    if center:
        cen_ids = [i for (i,) in db.query(Center.id)
                   .filter(Center.name.ilike(f"%{center.strip()}%")).all()]
        query = query.filter(model.center_id.in_(cen_ids)) if cen_ids else query.filter(text("1=0"))
    if village:
        vil_ids = [i for (i,) in db.query(Village.id)
                   .filter(Village.name.ilike(f"%{village.strip()}%")).all()]
        query = query.filter(model.village_id.in_(vil_ids)) if vil_ids else query.filter(text("1=0"))
    if surveyor:
        query = query.filter(model.surveyor_name.ilike(f"%{surveyor.strip()}%"))
    if office:
        query = query.filter(model.office_name.ilike(f"%{office.strip()}%"))
    if entry_from:
        d = _parse_date(entry_from)
        if d:
            query = query.filter(model.entry_date >= d)
    if entry_to:
        d = _parse_date(entry_to)
        if d:
            query = query.filter(model.entry_date <= d)
    if survey_from:
        d = _parse_date(survey_from)
        if d:
            query = query.filter(model.survey_date >= d)
    if survey_to:
        d = _parse_date(survey_to)
        if d:
            query = query.filter(model.survey_date <= d)
    sort_cols = {
        "id": model.id,
        "req_number": model.req_number,
        "applicant": model.applicant,
        "area_value": model.area_value,
        "request_status": model.request_status,
        "survey_status": model.survey_status,
        "entry_date": model.entry_date,
        "survey_date": model.survey_date,
    }
    if sort in sort_cols:
        col = sort_cols[sort]
        query = query.order_by(col.asc() if (dir or "").lower() == "asc" else col.desc())
    else:
        query = query.order_by(model.id.desc())
    return query


# Export columns: the shared template's headers in template order plus the
# legacy-export columns. Every header is a key HEADER_MAP (or its aliases)
# recognises, so an exported file re-imports through the same intake tool.
EXPORT_COLUMNS = (
    ("رقم الطلب", "req_number"),
    ("مقدم الطلب", "applicant"),
    ("الهاتف", "phone"),
    ("العنوان", "address"),
    ("المساحة", "area_value"),
    ("نوع المساحة", "area_unit"),
    ("نوع الوحدة", "unit_type"),
    ("المحافظة", "governorate"),
    ("المركز", "center"),
    ("القرية", "village"),
    ("المساح", "surveyor"),
    ("المكتب الفنى", "office"),
    ("الشركة", "company"),
    ("الحالة الطلب", "request_status"),
    ("حالة الرفع المساحي", "survey_status"),
    ("تعليق المكتب الفنى", "office_comment"),
    ("تعليق المكتب الفنى ميداني", "survey_comment"),
    ("رقم التقنين", "reqra_number"),
    ("تاريخ الادخال", "entry_date"),
    ("تاريخ الرفع المساحي", "survey_date"),
    ("تاريخ الرفع المساحى", "alt_survey_date"),
    ("تاريخ التوزيع", "distribution_date"),
    ("تاريخ الارسال جيوديسيا", "geodesy_date"),
    ("تاريخ الارسال للمديريه", "directorate_date"),
    ("علامات مميزة", "landmarks"),
    ("الفريق الميدانى", "field_team"),
    ("ملفات Raw", "raw_files"),
    ("BaseMap", "base_map"),
)


def _export_table(db: Session, items) -> tuple:
    """Table rows for EXPORT_COLUMNS — names resolved via bulk id->name maps."""
    gov_map = {g.id: g.name for g in db.query(Governorate).all()}
    cen_map = {c.id: c.name for c in db.query(Center).all()}
    vil_map = {v.id: v.name for v in db.query(Village).all()}
    unit_map = {u.id: u.name for u in db.query(AreaUnit).all()}

    def cell(v):
        if v is None:
            return ""
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        return v

    rows = []
    for r in items:
        vals = {
            "req_number": r.req_number,
            "applicant": r.applicant,
            "phone": r.phone,
            "address": r.address,
            "area_value": r.area_value,
            "area_unit": unit_map.get(r.area_unit_id),
            "unit_type": r.unit_type,
            "governorate": gov_map.get(r.governorate_id),
            "center": cen_map.get(r.center_id),
            "village": vil_map.get(r.village_id),
            "surveyor": r.surveyor_name,
            "office": r.office_name,
            "company": r.company,
            "request_status": r.request_status,
            "survey_status": r.survey_status,
            "office_comment": r.office_comment,
            "survey_comment": r.survey_comment,
            "reqra_number": r.reqra_number,
            "entry_date": r.entry_date,
            "survey_date": r.survey_date,
            "alt_survey_date": r.alt_survey_date,
            "distribution_date": r.distribution_date,
            "geodesy_date": r.geodesy_date,
            "directorate_date": r.directorate_date,
            "landmarks": r.landmarks,
            "field_team": r.field_team,
            "raw_files": r.raw_files,
            "base_map": r.base_map,
        }
        rows.append([cell(vals.get(key)) for _, key in EXPORT_COLUMNS])
    return [head for head, _ in EXPORT_COLUMNS], rows


def _csv_attachment(headers, rows, stem: str):
    """UTF-8-sig CSV download (opens cleanly in Excel), timestamped filename."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        io.BytesIO(data),
        headers={"Content-Disposition": f'attachment; filename="{stem}_{stamp}.csv"'},
        media_type="text/csv; charset=utf-8",
    )


@router.get("")
def list_requests(
    page: int = 1,
    per_page: int = 50,
    q: Optional[str] = None,
    governorate_id: Optional[int] = None,
    center_id: Optional[int] = None,
    village_id: Optional[int] = None,
    request_status: Optional[str] = None,
    survey_status: Optional[str] = None,
    surveyor_id: Optional[int] = None,
    office_id: Optional[int] = None,
    assigned_to_me: bool = False,
    has_geometry: Optional[bool] = None,
    governorate: Optional[str] = None,
    center: Optional[str] = None,
    village: Optional[str] = None,
    surveyor: Optional[str] = None,
    office: Optional[str] = None,
    entry_from: Optional[str] = None,
    entry_to: Optional[str] = None,
    survey_from: Optional[str] = None,
    survey_to: Optional[str] = None,
    sort: Optional[str] = None,
    dir: Optional[str] = None,
    ids: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    query = _apply_list_filters(
        db.query(CadastralRequest), db, current_user, CadastralRequest,
        q=q, governorate_id=governorate_id, center_id=center_id, village_id=village_id,
        request_status=request_status, survey_status=survey_status,
        surveyor_id=surveyor_id, office_id=office_id,
        assigned_to_me=assigned_to_me, has_geometry=has_geometry,
        governorate=governorate, center=center, village=village,
        surveyor=surveyor, office=office,
        entry_from=entry_from, entry_to=entry_to,
        survey_from=survey_from, survey_to=survey_to,
        sort=sort, dir=dir, ids=ids,
    )

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    geom = _bulk_geometry(db, [r.req_number for r in items])
    counts = _bulk_geometry_counts(db, [r.req_number for r in items])
    out = []
    for r in items:
        g = geom.get(r.req_number, [])
        item = _request_out(r, g, counts.get(r.req_number, 0))
        _attach_names(db, item, r)
        out.append(item)
    return {"items": out, "total": total, "page": page, "per_page": per_page}


@router.get("/stats")
def request_stats(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    today = date.today()
    total = db.query(func.count(CadastralRequest.id)).scalar() or 0
    today_imported = db.query(func.count(CadastralRequest.id)).filter(
        func.date(CadastralRequest.entry_date) == today
    ).scalar() or 0
    pending = db.query(func.count(CadastralRequest.id)).filter(
        CadastralRequest.request_status == "جديد"
    ).scalar() or 0
    in_survey = db.query(func.count(CadastralRequest.id)).filter(
        CadastralRequest.survey_status.isnot(None),
        CadastralRequest.survey_status != "",
    ).scalar() or 0
    tech_office = db.query(func.count(CadastralRequest.id)).filter(
        or_(CadastralRequest.office_name.isnot(None),
            CadastralRequest.assigned_office_id.isnot(None))
    ).scalar() or 0
    rejected_today = db.query(func.count(CadastralRequest.id)).filter(
        CadastralRequest.request_status == "مرفوض",
        func.date(CadastralRequest.status_updated_at) == today,
    ).scalar() or 0
    accepted_today = db.query(func.count(CadastralRequest.id)).filter(
        CadastralRequest.request_status == "مقبول",
        func.date(CadastralRequest.status_updated_at) == today,
    ).scalar() or 0

    by_status = dict(db.execute(
        text('SELECT "Request_Status", COUNT(*) FROM requests GROUP BY "Request_Status"')
    ).fetchall())
    by_center = [{"name": name, "count": n} for name, n in db.execute(
        text('''SELECT c.name, COUNT(*) FROM requests r LEFT JOIN centers c ON c.id = r."Center_Id"
                GROUP BY c.name ORDER BY COUNT(*) DESC LIMIT 8''')
    ).fetchall()]

    return {
        "total": total,
        "today_imported": today_imported,
        "pending": pending,
        "in_survey": in_survey,
        "tech_office": tech_office,
        "rejected_today": rejected_today,
        "accepted_today": accepted_today,
        "by_status": {k: v for k, v in by_status.items()},
        "by_center": by_center,
    }


# Declared before "/{request_id}" so the literal paths are not swallowed by the
# int path parameter.
@router.get("/export")
def export_requests_csv(
    q: Optional[str] = None,
    governorate_id: Optional[int] = None,
    center_id: Optional[int] = None,
    village_id: Optional[int] = None,
    request_status: Optional[str] = None,
    survey_status: Optional[str] = None,
    surveyor_id: Optional[int] = None,
    office_id: Optional[int] = None,
    assigned_to_me: bool = False,
    has_geometry: Optional[bool] = None,
    governorate: Optional[str] = None,
    center: Optional[str] = None,
    village: Optional[str] = None,
    surveyor: Optional[str] = None,
    office: Optional[str] = None,
    entry_from: Optional[str] = None,
    entry_to: Optional[str] = None,
    survey_from: Optional[str] = None,
    survey_to: Optional[str] = None,
    sort: Optional[str] = None,
    dir: Optional[str] = None,
    ids: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Download every request matching the list filters as a CSV sheet."""
    query = _apply_list_filters(
        db.query(CadastralRequest), db, current_user, CadastralRequest,
        q=q, governorate_id=governorate_id, center_id=center_id, village_id=village_id,
        request_status=request_status, survey_status=survey_status,
        surveyor_id=surveyor_id, office_id=office_id,
        assigned_to_me=assigned_to_me, has_geometry=has_geometry,
        governorate=governorate, center=center, village=village,
        surveyor=surveyor, office=office,
        entry_from=entry_from, entry_to=entry_to,
        survey_from=survey_from, survey_to=survey_to,
        sort=sort, dir=dir, ids=ids,
    )
    items = query.all()
    headers, rows = _export_table(db, items)
    return _csv_attachment(headers, rows, "requests_company")


@router.get("/import-template")
def download_import_template(
    current_user: User = Depends(deps.get_current_user),
):
    """Blank .xlsx for filling in new requests, with the exact expected headers."""
    from fastapi.responses import Response
    from app.api.import_template import build_requests_template

    body = build_requests_template("company")
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="company_requests_template.xlsx"'},
    )


@router.get("/import-result-template")
def download_import_result_template(
    current_user: User = Depends(deps.get_current_user),
):
    """Blank .xlsx for importing survey results against existing requests."""
    from fastapi.responses import Response
    from app.api.import_template import build_results_template

    body = build_results_template()
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="request_results_template.xlsx"'},
    )


@router.get("/{request_id}")
def get_request(
    request_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    r = db.query(CadastralRequest).filter(CadastralRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    geom = _bulk_geometry(db, [r.req_number]).get(r.req_number, [])
    item = _request_out(r, geom, _bulk_geometry_counts(db, [r.req_number]).get(r.req_number, 0))
    _attach_names(db, item, r)
    item["assigned_to"] = _assignee_name(db, r)
    history = db.query(AuditTrail).filter(
        AuditTrail.table_name == "requests",
        AuditTrail.record_id == request_id,
    ).order_by(AuditTrail.id.desc()).all()
    item["history"] = [
        {
            "action": h.action,
            "username": h.username,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "old_values": json.loads(h.old_values) if h.old_values else None,
            "new_values": json.loads(h.new_values) if h.new_values else None,
        }
        for h in history
    ]
    return item


@router.get("/{request_id}/has-geometry")
def request_has_geometry(
    request_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    r = db.query(CadastralRequest).filter(CadastralRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    return {
        "req_number": r.req_number,
        "layers": _bulk_geometry(db, [r.req_number]).get(r.req_number, []),
        "count": _bulk_geometry_counts(db, [r.req_number]).get(r.req_number, 0),
    }


@router.post("")
def create_request(
    body: RequestCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    body.req_number = (body.req_number or "").strip()
    if not body.req_number:
        raise HTTPException(status_code=400, detail="رقم الطلب مطلوب")
    if db.query(CadastralRequest).filter(CadastralRequest.req_number == body.req_number).first():
        raise HTTPException(status_code=400, detail=f"الطلب {body.req_number} موجود بالفعل")

    gov_code, center_code = _parse_req_codes(body.req_number)
    gov = _find_gov_by_code(db, gov_code) or (
        db.query(Governorate).filter(Governorate.name == (body.governorate or "")).first()
        if body.governorate else None
    )
    gov_id = gov.id if gov else get_or_create_governorate(db, body.governorate, gov_code)
    center_id = get_or_create_center(db, gov_id, body.center, center_code)
    village_id = get_or_create_village(db, center_id, body.village)

    r = CadastralRequest(
        req_number=body.req_number,
        applicant=body.applicant,
        phone=body.phone,
        address=body.address,
        area_value=body.area_value,
        area_unit_id=_resolve_area_unit(db, body.area_unit),
        unit_type=body.unit_type,
        governorate_id=gov_id,
        center_id=center_id,
        village_id=village_id,
        surveyor_name=body.surveyor,
        office_name=body.office,
        assigned_surveyor_id=_resolve_person(db, body.surveyor),
        assigned_office_id=_resolve_person(db, body.office),
        survey_status=body.survey_status,
        survey_comment=body.survey_comment,
        office_comment=body.office_comment,
        request_status=_snap_status(body.request_status, REQUEST_STATUSES) or "جديد",
        reqra_number=body.reqra_number,
        entry_date=_parse_date(body.entry_date) or date.today(),
        survey_date=_parse_date(body.survey_date),
        status_updated_at=datetime.utcnow(),
        imported_by_id=current_user.id,
        created_by=current_user.username,
    )
    db.add(r)
    db.flush()
    _audit(db, current_user, r.id, "CREATE", new={"req_number": r.req_number, "request_status": r.request_status})
    geom_n = _bulk_geometry_counts(db, [r.req_number], GEOM_TABLES).get(r.req_number, 0)
    r.base_map = BASEMAP_WITH_GEOM if geom_n else BASEMAP_WITHOUT_GEOM
    db.commit()
    db.refresh(r)
    item = _request_out(r, None)
    _attach_names(db, item, r)
    return item


@router.patch("/{request_id}")
def update_request(
    request_id: int,
    body: RequestUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    r = db.query(CadastralRequest).filter(CadastralRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    old = {"req_number": r.req_number, "applicant": r.applicant, "request_status": r.request_status}
    changes = {}

    # The edit form sends "" from a dropdown's empty option to clear a field;
    # None means "leave as-is". Consume the clearers here so "" can never reach
    # get_or_create_* (a code-derived centre would otherwise resurrect itself)
    # and every clear lands as a NULL with its own audit entry.
    cleared = set()
    for name, column in (("applicant", "applicant"), ("phone", "phone"), ("address", "address"),
                         ("unit_type", "unit_type"), ("survey_status", "survey_status"),
                         ("survey_comment", "survey_comment"), ("office_comment", "office_comment"),
                         ("request_status", "request_status"), ("reqra_number", "reqra_number"),
                         ("governorate", "governorate_id"), ("center", "center_id"),
                         ("village", "village_id"), ("area_unit", "area_unit_id"),
                         ("surveyor", "surveyor_name"), ("office", "office_name"),
                         ("entry_date", "entry_date"), ("survey_date", "survey_date"),
                         ("distribution_date", "distribution_date"),
                         ("alt_survey_date", "alt_survey_date"),
                         ("geodesy_date", "geodesy_date"),
                         ("directorate_date", "directorate_date"),
                         ("landmarks", "landmarks"), ("field_team", "field_team"),
                         ("raw_files", "raw_files"), ("base_map", "base_map")):
        if getattr(body, name, None) == "":
            setattr(body, name, None)
            cleared.add(name)
            if getattr(r, column) is not None:
                setattr(r, column, None)
                changes[name] = None

    # Clearing the name must also release the person it resolved to, or the
    # row would keep an owner the form no longer shows (and never re-claims).
    if "surveyor" in cleared:
        r.assigned_surveyor_id = None
    if "office" in cleared:
        r.assigned_office_id = None

    def set_if(field, value):
        nonlocal changes
        if value is not None:
            before = getattr(r, field)
            if before != value:
                setattr(r, field, value)
                changes[field] = value

    set_if("applicant", body.applicant)
    set_if("phone", body.phone)
    set_if("address", body.address)
    set_if("area_value", body.area_value)
    if "area_value" in (body.model_fields_set or set()) and body.area_value is None and r.area_value is not None:
        r.area_value = None
        changes["area_value"] = None
    set_if("unit_type", body.unit_type)
    set_if("survey_status", body.survey_status)
    set_if("survey_comment", body.survey_comment)
    set_if("office_comment", body.office_comment)
    set_if("request_status", body.request_status)
    # The status select replaces the old Change-status card, so a status
    # written here must stamp the same "last status change" the transition
    # endpoint would (the daily counters read Status_Updated_At).
    if "request_status" in changes:
        r.status_updated_at = datetime.utcnow()
    set_if("reqra_number", body.reqra_number)
    set_if("landmarks", body.landmarks)
    set_if("field_team", body.field_team)
    set_if("raw_files", body.raw_files)
    set_if("base_map", body.base_map)
    if body.area_unit is not None:
        uid = _resolve_area_unit(db, body.area_unit)
        if r.area_unit_id != uid:
            r.area_unit_id = uid
            changes["area_unit"] = body.area_unit
    if body.governorate is not None or body.center is not None or body.village is not None:
        gov_code, center_code = _parse_req_codes(r.req_number)
        gov_id = r.governorate_id
        if body.governorate is not None:
            gov = db.query(Governorate).filter(Governorate.name == body.governorate).first()
            gov_id = gov.id if gov else get_or_create_governorate(db, body.governorate, gov_code)
        center_id = r.center_id
        if body.center is not None:
            center_id = get_or_create_center(db, gov_id, body.center, center_code)
        village_id = r.village_id
        if body.village is not None:
            village_id = get_or_create_village(db, center_id, body.village)
        if body.governorate is not None and r.governorate_id != gov_id:
            r.governorate_id = gov_id
            changes["governorate"] = body.governorate
        if body.center is not None and r.center_id != center_id:
            r.center_id = center_id
            changes["center"] = body.center
        if body.village is not None and r.village_id != village_id:
            r.village_id = village_id
            changes["village"] = body.village
    if body.surveyor is not None and r.surveyor_name != body.surveyor:
        r.surveyor_name = body.surveyor
        r.assigned_surveyor_id = _resolve_person(db, body.surveyor)
        changes["surveyor"] = body.surveyor
    if body.office is not None and r.office_name != body.office:
        r.office_name = body.office
        r.assigned_office_id = _resolve_person(db, body.office)
        changes["office"] = body.office
    if body.entry_date is not None:
        d = _parse_date(body.entry_date)
        if d and d != r.entry_date:
            r.entry_date = d
            changes["entry_date"] = body.entry_date
    if body.survey_date is not None:
        d = _parse_date(body.survey_date)
        if d and d != r.survey_date:
            r.survey_date = d
            changes["survey_date"] = body.survey_date
    for name in ("distribution_date", "alt_survey_date", "geodesy_date", "directorate_date"):
        value = getattr(body, name, None)
        if value is not None:
            d = _parse_date(value)
            if d and d != getattr(r, name):
                setattr(r, name, d)
                changes[name] = value

    _require_acceptable(r)
    _require_date_order(r)
    _require_staff(r)
    if changes:
        _claim_if_unassigned(r, changes, current_user)
        _audit(db, current_user, r.id, "UPDATE", old=old, new={**old, **changes})
    db.commit()
    db.refresh(r)
    item = _request_out(r, None)
    _attach_names(db, item, r)
    item["assigned_to"] = _assignee_name(db, r)
    return item


@router.post("/{request_id}/transition")
def transition_request(
    request_id: int,
    body: TransitionIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    r = db.query(CadastralRequest).filter(CadastralRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    target = (body.to or "").strip()
    if target not in REQUEST_STATUSES:
        raise HTTPException(status_code=400, detail=f"حالة غير صالحة: {target}")
    old = r.request_status
    if old == target:
        raise HTTPException(status_code=400, detail="الحالة نفسها بلا تغيير")
    r.request_status = target
    r.status_updated_at = datetime.utcnow()
    new_values = {"req_number": r.req_number, "request_status": target}
    if body.comment:
        new_values["comment"] = body.comment
    _require_acceptable(r)
    # A status change is an edit too: it claims an unowned request.
    _claim_if_unassigned(r, new_values, current_user)
    _audit(db, current_user, r.id, "TRANSITION", old={"request_status": old}, new=new_values)
    assignee = r.assigned_surveyor_id or r.assigned_office_id
    if assignee and assignee != current_user.id:
        _notify_user(db, assignee, "transition",
                     f"تغيّرت حالة الطلب {r.req_number} إلى {target}",
                     (body.comment or "").strip() or f"بواسطة {current_user.username}",
                     link_req=f"company:{r.req_number}")
    db.commit()
    db.refresh(r)
    return {"id": r.id, "req_number": r.req_number, "request_status": r.request_status,
            "assigned_to": _assignee_name(db, r)}


@router.post("/bulk-assign")
def bulk_assign_requests(
    body: BulkAssignIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    """Assign many requests to a surveyor and/or office by name."""
    ids = [i for i in (body.ids or []) if isinstance(i, int) and i > 0][:2000]
    if not ids:
        raise HTTPException(status_code=400, detail="No request ids provided")
    surveyor = (body.surveyor or "").strip() or None
    office = (body.office or "").strip() or None
    if not surveyor and not office:
        raise HTTPException(status_code=400, detail="Provide a surveyor or an office")
    s_id = _resolve_person(db, surveyor) if surveyor else None
    o_id = _resolve_person(db, office) if office else None
    updated = 0
    for r in db.query(CadastralRequest).filter(CadastralRequest.id.in_(ids)).all():
        changes = {}
        if surveyor is not None:
            if r.surveyor_name != surveyor:
                changes["surveyor"] = surveyor
            r.surveyor_name = surveyor
            r.assigned_surveyor_id = s_id
        if office is not None:
            if r.office_name != office:
                changes["office"] = office
            r.office_name = office
            r.assigned_office_id = o_id
        if changes:
            changes["req_number"] = r.req_number
            _audit(db, current_user, r.id, "ASSIGN", new=changes)
            target_uid = s_id or o_id
            if target_uid and target_uid != current_user.id:
                _notify_user(db, target_uid, "assign",
                             f"تم إسناد الطلب {r.req_number} إليك",
                             f"بواسطة {current_user.username}",
                             link_req=f"company:{r.req_number}")
            updated += 1
    db.commit()
    return {"updated": updated}


@router.post("/bulk-transition")
def bulk_transition_requests(
    body: BulkTransitionIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    """Move many requests to one status, with an optional shared comment."""
    ids = [i for i in (body.ids or []) if isinstance(i, int) and i > 0][:2000]
    if not ids:
        raise HTTPException(status_code=400, detail="No request ids provided")
    target = (body.to or "").strip()
    if target not in REQUEST_STATUSES:
        raise HTTPException(status_code=400, detail=f"حالة غير صالحة: {target}")
    comment = (body.comment or "").strip() or None
    rows = db.query(CadastralRequest).filter(CadastralRequest.id.in_(ids)).all()
    if target == "مقبول":
        bad = [r.req_number for r in rows
               if r.request_status != target
               and ((r.survey_status or "").strip() not in ACCEPTED_SURVEY_STATUSES
                    or not (r.surveyor_name or "").strip()
                    or not r.entry_date)]
        if bad:
            raise HTTPException(status_code=400, detail=f"{len(bad)} طلب لا يستوفي شروط القبول (تم المعاينة + مساح + تاريخ الإدخال)")
    updated = 0
    for r in rows:
        if r.request_status == target:
            continue
        old = r.request_status
        r.request_status = target
        r.status_updated_at = datetime.utcnow()
        new_values = {"req_number": r.req_number, "request_status": target}
        if comment:
            new_values["comment"] = comment
        _claim_if_unassigned(r, new_values, current_user)
        _audit(db, current_user, r.id, "TRANSITION", old={"request_status": old}, new=new_values)
        assignee = r.assigned_surveyor_id or r.assigned_office_id
        if assignee and assignee != current_user.id:
            _notify_user(db, assignee, "transition",
                         f"تغيّرت حالة الطلب {r.req_number} إلى {target}",
                         comment or f"بواسطة {current_user.username}",
                         link_req=f"company:{r.req_number}")
        updated += 1
    db.commit()
    return {"updated": updated}


@router.post("/import")
def import_requests(
    file: UploadFile = File(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
    force: bool = False,
):
    raw = file.file.read()
    unmapped: set = set()
    parsed = parse_sheet(raw, file.filename or "sheet.csv", unmapped_out=unmapped)
    if not force:
        _reject_unmapped_sheet(parsed, unmapped)
    if not parsed:
        raise HTTPException(status_code=400, detail="لا توجد صفوف قابلة للقراءة في الملف")

    added, updated, duplicated, errors = [], [], [], []
    skipped_no_number = 0
    created_out: dict = {}
    for row in parsed:
        req_number = _to_ascii_digits(row.get("req_number", "") or "").strip()
        if not req_number:
            # The template ships a status reference list below the header row.
            # Those rows carry a status but no business key, so skip them
            # quietly instead of reporting them as import errors.
            skipped_no_number += 1
            continue
        # A failing row rolls its SAVEPOINT back, including any lookup it had
        # just created — restore the report so it does not claim a phantom.
        snapshot = {k: list(v) for k, v in created_out.items()}
        try:
            # Everything that touches the database runs inside a SAVEPOINT: a
            # failing row must roll back only itself, never (silently) the rows
            # imported before it, and never poison the outer transaction.
            with db.begin_nested():
                existing = db.query(CadastralRequest).filter(CadastralRequest.req_number == req_number).first()
                if existing is not None:
                    # Same update-in-place policy as the mudryia ledger: a
                    # re-imported sheet fills what the stored row is missing
                    # instead of being counted and dropped as a duplicate.
                    changes = _fill_request_from_sheet_row(db, existing, row, req_number, current_user,
                                                           created_out=created_out)
                else:
                    changes = None
                    values = _request_row_values(db, row, req_number, current_user,
                                                 created_out=created_out)
                    values["entry_date"] = values["entry_date"] or date.today()
                    r = CadastralRequest(req_number=req_number, **values)
                    db.add(r)
                    db.flush()
                    _audit(db, current_user, r.id, "IMPORT", new={"req_number": req_number, "request_status": r.request_status})
            if existing is not None:
                (updated if changes else duplicated).append(req_number)
            else:
                added.append(req_number)
        except Exception as exc:  # noqa: BLE001
            created_out.clear()
            created_out.update(snapshot)
            errors.append({"reason": str(exc), "req_number": req_number})
    if added:
        _notify_all(db, "import",
                    title="استيراد جديد لشيت الطلبات",
                    body=f"تم استيراد {len(added)} طلبًا جديدًا")

    db.commit()

    try:
        sync_base_map_bulk(db, added + updated + duplicated)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"Base_Map sync failed after import: {exc}")

    rows_with_no, seen, avg_fields, missing = _sheet_coverage(parsed)
    return {
        "added": len(added),
        "updated": len(updated),
        "duplicated": len(duplicated),
        "errors": len(errors),
        "added_numbers": added[:50],
        "updated_numbers": updated[:50],
        "duplicates": duplicated[:50],
        "error_details": errors[:20],
        # Same reporting as the mudryia ledger, so one template and one guard
        # behave identically on both.
        "unmapped_columns": sorted(unmapped),
        "skipped_no_number": skipped_no_number,
        "rows_with_number": rows_with_no,
        "mapped_fields": sorted(seen),
        "missing_fields": missing,
        "avg_fields_per_row": round(avg_fields, 2),
        # Lookup values this import had to add to the shared lookups tables.
        "created_lookups": created_out,
    }


@router.post("/import-result")
def import_result(
    file: UploadFile = File(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    raw = file.file.read()
    parsed = parse_sheet(raw, file.filename or "result.csv", kind="result")
    if not parsed:
        raise HTTPException(status_code=400, detail="لا توجد صفوف قابلة للقراءة في الملف")

    updated, not_found, errors = [], [], []
    skipped_no_number = 0
    rejected = 0
    accepted = 0
    for row in parsed:
        req_number = _to_ascii_digits(row.get("req_number", "") or "").strip()
        if not req_number:
            # The template ships a status reference list below the header row.
            # Those rows carry a status but no business key, so skip them
            # quietly instead of reporting them as import errors.
            skipped_no_number += 1
            continue
        r = db.query(CadastralRequest).filter(CadastralRequest.req_number == req_number).first()
        if not r:
            not_found.append(req_number)
            continue
        result = str(row.get("result") or row.get("request_status") or "").strip()
        if not result:
            errors.append({"reason": "missing_result", "req_number": req_number})
            continue
        if "مرفوض" in result:
            result = "مرفوض"
        elif "مقبول" in result:
            result = "مقبول"
        old = r.request_status
        new_status = result if result in REQUEST_STATUSES else r.request_status
        r.request_status = new_status
        if row.get("reqra_number"):
            r.reqra_number = str(row["reqra_number"]).strip()
        r.status_updated_at = datetime.utcnow()
        _audit(db, current_user, r.id, "IMPORT_RESULT",
               old={"request_status": old},
               new={"request_status": new_status, "reqra_number": r.reqra_number})
        updated.append(req_number)
        if new_status == "مرفوض":
            rejected += 1
        elif new_status == "مقبول":
            accepted += 1
    if updated:
        _notify_all(db, "result",
                    title="تحديث نتيجة الطلبات",
                    body=f"تم تحديث نتيجة {len(updated)} طلبًا — {accepted} مقبول | {rejected} مرفوض")

    db.commit()

    return {
        "updated": len(updated),
        "not_found": len(not_found),
        "errors": len(errors),
        "rejected": rejected,
        "accepted": accepted,
        "updated_numbers": updated[:50],
        "not_found_numbers": not_found[:50],
    }


def _notify_all(db: Session, ntype: str, title: str, body: str):
    users = db.query(User).filter(User.is_active == True).all()  # noqa: E712
    for u in users:
        db.add(Notification(
            user_id=u.id,
            type=ntype,
            title=title,
            body=body,
            link_req=None,
        ))