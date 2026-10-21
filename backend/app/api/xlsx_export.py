"""Polished Excel export for the request ledgers (company + mudryia).

The ledgers used to export a plain CSV, which cannot carry any formatting.
This module builds a .xlsx instead: a coloured header row, frozen and
filterable columns, real Excel dates, a colour per request status and a
second "معلومات" sheet describing the export.

The file still re-imports through the same intake tool — the importer reads
every sheet but only processes the ones that carry a "رقم الطلب" column, and
the data sheet is always the first one.
"""

from datetime import date, datetime
from io import BytesIO

# Same header colour as the intake template, so both files look alike.
HEADER_FILL = "1F4E79"
HEADER_FONT = "FFFFFF"
ZEBRA_FILL = "F8FAFC"

# Columns written as text so Excel cannot reformat them (a phone number must
# keep its leading zero, a request number its exact digits).
TEXT_KEYS = ("req_number", "reqra_number", "phone")
# Numeric columns with a plain number format.
NUM_KEYS = ("area_value",)
# Free-text columns that get a wider, wrapped cell.
COMMENT_KEYS = ("survey_comment", "office_comment")

# Status colouring: (cell fill, font colour). Unknown statuses keep the
# default look, so a new managed status never breaks the export.
STATUS_COLORS = {
    "request_status": {
        "مقبول": ("DCFCE7", "166534"),
        "مرفوض": ("FEE2E2", "991B1B"),
        "قيد الدراسة": ("FEF3C7", "92400E"),
        "قيد المعاينة": ("FEF3C7", "92400E"),
        "جديد": ("E0F2FE", "075985"),
        "مكتمل ولم يرسل": ("E0E7FF", "3730A3"),
        "تم الارسال": ("CFFAFE", "155E75"),
        "جاري العمل عليه": ("E0E7FF", "3730A3"),
        "لم يتم الارسال": ("F1F5F9", "475569"),
        "لم يتم العمل عليه": ("F1F5F9", "475569"),
        "لا يوجد": ("F1F5F9", "475569"),
    },
    "survey_status": {
        "تم المعاينة": ("DCFCE7", "166534"),
        "تمت المعاينة": ("DCFCE7", "166534"),
        "تم المعاينه": ("DCFCE7", "166534"),
        "تم الرفع وجاري المراجعة": ("FEF3C7", "92400E"),
        "لم يتم المعاينه": ("F1F5F9", "475569"),
        "لم يتم العمل عليه": ("F1F5F9", "475569"),
        "اعاده معاينه": ("FEF3C7", "92400E"),
        "تعذر الرفع": ("FFEDD5", "9A3412"),
        "ملف غير مكتمل": ("FEF3C7", "92400E"),
        "مرفوض مكتب فني": ("FEE2E2", "991B1B"),
    },
}

# Arabic labels for the filters, so the "معلومات" sheet reads like the app.
FILTER_LABELS = {
    "q": "بحث",
    "request_status": "حالة الطلب",
    "survey_status": "حالة المعاينة",
    "has_geometry": "وجود خريطة",
    "governorate": "المحافظة",
    "center": "المركز",
    "village": "القرية",
    "surveyor": "المساح",
    "office": "المكتب الفني",
    "unit_type": "نوع الوحدة",
    "survey_comment": "بحث في تعليق المعاينة",
    "survey_comment_state": "تعليق المعاينة",
    "office_comment": "بحث في تعليق المكتب الفني",
    "office_comment_state": "تعليق المكتب الفني",
    "entry_from": "إدخال من",
    "entry_to": "إدخال إلى",
    "survey_from": "رفع ميدانى من",
    "survey_to": "رفع ميدانى إلى",
    "directorate_from": "إرسال مديرية من",
    "directorate_to": "إرسال مديرية إلى",
    "assigned_to_me": "طلباتي",
    "ids": "صفوف محددة",
    "sort": "الترتيب",
    "dir": "اتجاه الترتيب",
}


def _is_date(value) -> bool:
    return isinstance(value, (date, datetime))


def applied_filters(scope: dict) -> dict:
    """The filters that were actually applied, with Arabic labels."""
    out = {}
    for name, label in FILTER_LABELS.items():
        value = scope.get(name)
        if value in (None, "", [], False):
            continue
        out[label] = value
    return out


def build_ledger_workbook(headers, rows, keys, meta=None, sheet_title="الطلبات") -> bytes:
    """Build the styled workbook for one ledger export.

    ``headers`` are the column titles, ``keys`` the matching field keys (they
    decide the date/number/text/status formatting) and ``rows`` the raw cell
    values (dates as date objects, None for an empty cell).
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.sheet_view.rightToLeft = True

    ncols = len(headers)

    # --- header row
    head_fill = PatternFill("solid", fgColor=HEADER_FILL)
    head_font = Font(color=HEADER_FONT, bold=True, size=11)
    head_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for c, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c, value=title)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = head_align
    ws.row_dimensions[1].height = 34
    ws.freeze_panes = "A2"

    # --- data rows
    zebra_fill = PatternFill("solid", fgColor=ZEBRA_FILL)
    for r, row in enumerate(rows, start=2):
        striped = (r % 2) == 1
        for c, (key, value) in enumerate(zip(keys, row), start=1):
            cell = ws.cell(row=r, column=c)
            if value is None:
                cell.value = ""
            elif _is_date(value):
                cell.value = value
                cell.number_format = "yyyy-mm-dd"
            elif key in TEXT_KEYS:
                cell.value = str(value)
                cell.number_format = "@"
            elif key in NUM_KEYS and isinstance(value, (int, float)):
                cell.value = value
                cell.number_format = "0.###"
            else:
                cell.value = value
            tone = STATUS_COLORS.get(key, {}).get(str(value).strip() if value is not None else "")
            if tone:
                cell.fill = PatternFill("solid", fgColor=tone[0])
                cell.font = Font(color=tone[1], bold=True)
            elif striped:
                cell.fill = zebra_fill
            if key in COMMENT_KEYS:
                cell.alignment = Alignment(vertical="top", wrap_text=True)

    # --- column widths (sampled from the first rows, then the comment columns)
    widths = [max(12, min(45, len(str(h)) + 4)) for h in headers]
    for row in rows[:200]:
        for c, value in enumerate(row):
            text = "" if value is None else str(value)
            if len(text) + 2 > widths[c]:
                widths[c] = min(45, len(text) + 2)
    for c, key in enumerate(keys):
        if key in COMMENT_KEYS:
            widths[c] = max(widths[c], 35)
    for c in range(ncols):
        ws.column_dimensions[get_column_letter(c + 1)].width = widths[c]

    last_col = get_column_letter(ncols)
    if rows:
        ws.auto_filter.ref = f"A1:{last_col}{len(rows) + 1}"

    # --- second sheet: what was exported
    if meta:
        info = wb.create_sheet("معلومات")
        info.sheet_view.rightToLeft = True
        info["A1"] = meta.get("title") or "تصدير سجل الطلبات"
        info["A1"].font = Font(bold=True, size=14, color=HEADER_FILL)
        info["A2"] = "عدد السجلات"
        info["B2"] = meta.get("rows", len(rows))
        info["A3"] = "وقت التصدير"
        info["B3"] = meta.get("generated_at")
        info["A4"] = "الفلاتر المطبّقة"
        info["B4"] = "، ".join(f"{k}: {v}" for k, v in (meta.get("filters") or {}).items()) or "بدون فلاتر"
        info["A5"] = "ملاحظة"
        info["B5"] = meta.get("note") or "الملف جاهز للاستيراد من صفحة الاستيراد."
        for r in range(2, 6):
            info.cell(row=r, column=1).font = Font(bold=True, size=10)
            info.cell(row=r, column=2).alignment = Alignment(vertical="top", wrap_text=True)
        info.column_dimensions["A"].width = 22
        info.column_dimensions["B"].width = 70

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
