"""Downloadable .xlsx templates for the request ledgers.

The intake template is the one the user maintains at
``docs/template.xlsx`` and it governs **both** ledgers, so the header row below is
that file's header row, in that file's order, spelled that way — including the
column the user added at position 6 and the repeated comment column at
position 20. Do not reorder or "tidy" it: the point is that the sheet a user
already has imports without renaming anything.

The generated file adds one thing over the hand-made original: the status
reference lists the user typed into rows 3-7 become real Excel dropdowns on the
columns they belong to, and the data sheet is left with the header row only.
That way the same values are available while filling the sheet, and no reference
row can be mistaken for a data row.

Header matching is tolerant (see app.api.requests), so a hand-edited sheet that
spells a header slightly differently still imports.
"""

import io

from app.db.models import REQUEST_STATUSES

# Column order taken verbatim from docs/template.xlsx (the user's file).
TEMPLATE_HEADERS = (
    "رقم الطلب",
    "العنوان",
    "المساحة",
    "نوع المساحة",
    "نوع الوحدة",
    "تاريخ الرفع المساحي",
    "الهاتف",
    "مقدم الطلب",
    "رقم التقنين",
    "المحافظة",
    "المركز",
    "القرية",
    "المساح",
    "تاريخ  الرفع",
    "حالة الرفع المساحي",
    "تعليق المكتب الفنى",
    "المكتب الفنى",
    "حالة الطلب",
    "تاريخ الادخال",
    "تعليق المكتب الفنى",
)

# The status values the user typed as reference rows in docs/template.xlsx, used
# verbatim as the in-cell dropdowns. These are deliberately NOT the app's wider
# REQUEST_STATUSES/SURVEY_STATUSES: the template offers the user's own short
# list, while those tuples also accept the older spellings that already exist in
# the ledgers.
TEMPLATE_REQUEST_STATUSES = (
    "قيد المعاينة",
    "بالمراجعة الفنية",
    "تم الارسال",
    "مقبول",
    "مرفوض",
)
TEMPLATE_SURVEY_STATUSES = (
    "لم يتم المعاينه",
    "تم المعاينه",
    "تعذر الرفع",
    "اعاده معاينه",
    "مرفوض مكتب فني",
)

# Per-column notes for the instructions sheet, keyed by header.
_NOTES = {
    "رقم الطلب": "مفتاح الطلب، يجب أن يكون فريدًا. منه تُستخرج المحافظة تلقائيًا وبه تُربط الطبقات.",
    "مقدم الطلب": "اسم صاحب الطلب، وهو حقل أساسي.",
    "الهاتف": "رقم الهاتف أو الجوال.",
    "العنوان": "وصف العنوان التفصيلي.",
    "المساحة": "رقم فقط، بدون وحدة القياس.",
    "نوع المساحة": "وحدة القياس: متر مربع، قيراط، سهم، فدان. وتُقبل أيضًا م2 وقيراط وسهم وفدان.",
    "نوع الوحدة": "نوع الوحدة العقارية إن وُجد.",
    "المحافظة": "تُؤخذ من رقم الطلب تلقائيًا. اتركها فارغًا؛ ويُستخدم نص هذا العمود فقط إن تعذّر استخراج المحافظة.",
    "المركز": "اسم المركز.",
    "القرية": "اسم القرية.",
    "الشركة": "اسم الشركة إن كان الطلب من شركة.",
    "المساح": "اسم المساح الذي قام بالمعاينة.",
    "المكتب الفنى": "المكتب الفني المسؤول عن الطلب.",
    "حالة الرفع المساحي": "اختر من القائمة: " + "، ".join(TEMPLATE_SURVEY_STATUSES) + ".",
    "حالة الطلب": "اختر من القائمة: " + "، ".join(TEMPLATE_REQUEST_STATUSES) + ".",
    "رقم التقنين": "رقم التقنين إن وُجد.",
    "تاريخ الادخال": "تاريخ إدخال الطلب بصيغة يوم/شهر/سنة.",
    "تاريخ الرفع المساحي": "تاريخ الرفع المساحي. يقبل أيضًا 2026-01-15 أو 15-01-2026.",
    "تاريخ  الرفع": "تاريخ الرفع — مرادف للعمود «تاريخ الرفع المساحي». املأ أحدهما فقط.",
}

_REQUIRED = {"رقم الطلب", "مقدم الطلب", "المساحة", "حالة الطلب", "تاريخ الادخال"}

_EXAMPLES = {
    "رقم الطلب": "B-Y25-2503-01-00000042613",
    "مقدم الطلب": "أحمد علي",
    "الهاتف": "0911234567",
    "العنوان": "شارع 중앙 - جانب البريد",
    "المساحة": "250",
    "نوع المساحة": "متر مربع",
    "نوع الوحدة": "استيطاني",
    "المحافظة": "",
    "المركز": "مركز حمص",
    "القرية": "البياع",
    "المساح": "م. خالد",
    "المكتب الفنى": "مكتب حمص",
    "حالة الرفع المساحي": "تم المعاينه",
    "حالة الطلب": "قيد المعاينة",
    "رقم التقنين": "12 / 34",
    "تاريخ الادخال": "15/01/2026",
    "تاريخ الرفع المساحي": "20/01/2026",
    "تاريخ  الرفع": "20/01/2026",
}

# Which columns get a dropdown, and the values offered.
_DROPDOWNS = {
    "حالة الطلب": TEMPLATE_REQUEST_STATUSES,
    "حالة الرفع المساحي": TEMPLATE_SURVEY_STATUSES,
}

RESULT_HEADERS = ("رقم الطلب", "النتيجة", "رقم التقنين")


def _style_header(ws, ncols: int) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    fill = PatternFill("solid", fgColor="1F4E79")
    font = Font(color="FFFFFF", bold=True, size=11)
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 34
    ws.freeze_panes = "A2"


def _add_dropdowns(ws, headers, nrows: int = 500) -> None:
    """Attach an in-cell dropdown to each status column.

    The values are written to a hidden lookup sheet rather than inline, so the
    data sheet keeps only the header row and no reference row can be imported
    as a request.
    """
    import openpyxl
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    for idx, header in enumerate(headers, start=1):
        values = _DROPDOWNS.get(header)
        if not values:
            continue
        col_letter = get_column_letter(idx)
        dv = DataValidation(
            type="list",
            formula1='"' + ",".join(values) + '"',
            allow_blank=True,
            showDropDown=False,
        )
        dv.error = "اختر قيمة من القائمة."
        dv.errorTitle = "قيمة غير مسموحة"
        ws.add_data_validation(dv)
        dv.add(f"{col_letter}2:{col_letter}{nrows}")


def build_requests_template(ledger: str = "company") -> bytes:
    """Build the intake template .xlsx shared by both ledgers."""
    import openpyxl
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    label = "طلبات المديرية (mudryia)" if ledger == "mudryia" else "طلبات الشركات (company)"
    headers = TEMPLATE_HEADERS

    wb = openpyxl.Workbook()

    # --- Sheet 1: the data sheet. Header row only.
    data = wb.active
    data.title = "البيانات"
    data.append(list(headers))
    _style_header(data, len(headers))
    for i, h in enumerate(headers, start=1):
        data.column_dimensions[get_column_letter(i)].width = max(15, len(h) + 5)
    data.cell(row=2, column=1).comment = Comment(
        "ابدأ الكتابة من الصف 2 ولا تحذف صف العناوين. "
        "الصفوف التي تكون كل خلاياها فارغة تُتجاهل تلقائيًا.",
        "MapViewer", height=110, width=330,
    )
    _add_dropdowns(data, headers)

    # --- Sheet 2: the column reference.
    ref = wb.create_sheet("التعليمات")
    ref["A1"] = "قالب استيراد " + label
    ref["A1"].font = Font(bold=True, size=14)
    ref["A2"] = ("املأ ورقة «البيانات» فقط. ورقة التعليمات هذه للاطلاع ولا تُستورد. "
                 "يجب أن تبقى عناوين الصف الأول كما هي.")
    ref["A2"].font = Font(size=10, italic=True)
    ref.append([])
    ref.append(["العمود", "إلزامي", "مثال", "الشرح"])
    for c in range(1, 5):
        cell = ref.cell(row=ref.max_row, column=c)
        cell.fill = PatternFill("solid", fgColor="1F4E79")
        cell.font = Font(color="FFFFFF", bold=True)

    seen = set()
    for h in headers:
        if h in seen:
            note = _NOTES.get(h, "") + " (مكرر: العمود الثاني يكتب في الحقل نفسه)"
            seen.add(h)
            ref.append([h, "لا", "", note])
            continue
        seen.add(h)
        ref.append([h, "نعم" if h in _REQUIRED else "لا", _EXAMPLES.get(h, ""), _NOTES.get(h, "")])

    ref.append([])
    ref.append(["ملاحظات عامة", "", "", ""])
    for n in (
        "الصفوف التي تكون كل خلاياها فارغة تُتجاهل تلقائيًا.",
        "التاريخ يقبل يوم/شهر/سنة، أو 2026-01-15، أو قيمة تاريخ من Excel.",
        "«تاريخ الرفع المساحي» و«تاريخ  الرفع» يعنيان التاريخ نفسه؛ املأ أحدهما فقط.",
        "أرقام الطلبات الموجودة مسبقًا تُتخطى تلقائيًا ولن تتكرر.",
        "إذا رفض الاستيراد ملفًا فسيعرض لك الأعمدة غير المعروفة بالاسم.",
    ):
        ref.append(["", "", "", "• " + n])

    ref.column_dimensions["A"].width = 26
    ref.column_dimensions["B"].width = 10
    ref.column_dimensions["C"].width = 32
    ref.column_dimensions["D"].width = 78
    for row in ref.iter_rows(min_row=5):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_results_template() -> bytes:
    """Build the survey-results template used by the «import result» endpoint."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    data = wb.active
    data.title = "النتائج"
    data.append(list(RESULT_HEADERS))
    _style_header(data, len(RESULT_HEADERS))
    for i, h in enumerate(RESULT_HEADERS, start=1):
        data.column_dimensions[get_column_letter(i)].width = max(18, len(h) + 8)

    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", formula1='"' + ",".join(REQUEST_STATUSES) + '"',
                        allow_blank=True, showDropDown=False)
    ws = data
    ws.add_data_validation(dv)
    dv.add("B2:B500")

    ref = wb.create_sheet("التعليمات")
    ref["A1"] = "قالب استيراد نتائج الرفع المساحي"
    ref["A1"].font = Font(bold=True, size=14)
    ref["A2"] = "ورقة «النتائج» للبيانات فقط. كل صف يحدّث حالة طلب واحد."
    ref["A2"].font = Font(size=10, italic=True)
    ref.append([])
    ref.append(["العمود", "إلزامي", "مثال", "الشرح"])
    for c in range(1, 5):
        cell = ref.cell(row=ref.max_row, column=c)
        cell.fill = PatternFill("solid", fgColor="1F4E79")
        cell.font = Font(color="FFFFFF", bold=True)
    for h, ex, note in (
        ("رقم الطلب", "B-Y25-2503-01-00000042613", "الطلب الذي تريد تحديث حالته."),
        ("النتيجة", "مقبول", "الحالة النهائية. اختر من القائمة."),
        ("رقم التقنين", "12 / 34", "رقم التقنين إن وُجد."),
    ):
        ref.append([h, "نعم" if h != "رقم التقنين" else "لا", ex, note])
    ref.append([])
    ref.append(["", "", "", "الحالات المقبولة: " + "، ".join(REQUEST_STATUSES)])
    for w, col in ((24, "A"), (10, "B"), (32, "C"), (70, "D")):
        ref.column_dimensions[col].width = w
    for row in ref.iter_rows(min_row=5):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
