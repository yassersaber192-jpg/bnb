"""قوالب Excel وقراءتها وكتابة تقرير النتيجة.

شكل القالب: الصف الأول أسماء الأعمدة (متغيّرهاش)، الصف التاني شرح بالعربي،
والبيانات من الصف التالت. كل صف = صنف واحد، والأصناف اللي ليها نفس رقم
الفاتورة/الإيصال بتتجمع في مستند واحد (بيانات العميل بتتاخد من أول صف).
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

INVOICE_COLUMNS = [
    ("internal_id", "رقم الفاتورة الداخلي *", "INV-001"),
    ("document_type", "النوع: I فاتورة / C إشعار دائن / D إشعار مدين", "I"),
    ("date", "تاريخ الفاتورة *", "2026-11-15"),
    ("receiver_type", "نوع العميل: B شركة / P فرد / F أجنبي", "B"),
    ("receiver_id", "الرقم الضريبي (9 أرقام) أو القومي", "200000000"),
    ("receiver_name", "اسم العميل *", "شركة العميل"),
    ("receiver_governate", "محافظة العميل", "Giza"),
    ("receiver_city", "مدينة العميل", "Dokki"),
    ("receiver_street", "شارع العميل", "شارع التحرير"),
    ("receiver_building", "رقم مبنى العميل", "5"),
    ("description", "وصف الصنف", "خدمات استشارية"),
    ("item_type", "نوع الكود: EGS أو GS1", "EGS"),
    ("item_code", "كود الصنف المسجل على المنظومة *", "EG-100000000-1"),
    ("internal_code", "الكود الداخلي (اختياري)", ""),
    ("unit_type", "وحدة القياس (EA وغيرها)", "EA"),
    ("quantity", "الكمية *", 2),
    ("unit_price", "سعر الوحدة قبل الضريبة *", 1000),
    ("discount_rate", "نسبة الخصم %", ""),
    ("discount_amount", "قيمة الخصم", ""),
    ("vat_rate", "نسبة القيمة المضافة (فاضي = 14)", 14),
    ("vat_subtype", "كود نوع الضريبة (فاضي = V009)", "V009"),
    ("wht_rate", "نسبة الخصم تحت حساب الضريبة % (لو موجود)", ""),
    ("wht_subtype", "كود الخصم تحت الحساب (فاضي = W010)", ""),
    ("items_discount", "خصم بعد الضريبة على الصنف", ""),
    ("extra_discount", "خصم إضافي على الفاتورة كلها", ""),
    ("reference_uuid", "UUID الفاتورة الأصلية (للإشعارات)", ""),
]

RECEIPT_COLUMNS = [
    ("receipt_number", "رقم الإيصال *", "R-0001"),
    ("receipt_type", "النوع: S بيع / R مرتجع", "S"),
    ("date", "تاريخ ووقت الإيصال *", "2026-11-15 10:30"),
    ("pos", "نقطة البيع (الاسم في الإعدادات) *", "main"),
    ("payment_method", "طريقة الدفع: C كاش / V فيزا / O أخرى", "C"),
    ("buyer_type", "نوع المشتري: P فرد / B شركة / F أجنبي", "P"),
    ("buyer_id", "رقم المشتري (مطلوب من 150,000)", ""),
    ("buyer_name", "اسم المشتري", ""),
    ("buyer_mobile", "موبايل المشتري", ""),
    ("description", "وصف الصنف", "منتج"),
    ("item_type", "نوع الكود: EGS أو GS1", "EGS"),
    ("item_code", "كود الصنف المسجل *", "EG-100000000-1"),
    ("internal_code", "الكود الداخلي (اختياري)", ""),
    ("unit_type", "وحدة القياس", "EA"),
    ("quantity", "الكمية *", 1),
    ("unit_price", "سعر الوحدة قبل الضريبة *", 100),
    ("discount_amount", "قيمة الخصم", ""),
    ("vat_rate", "نسبة القيمة المضافة (فاضي = 14)", 14),
    ("vat_subtype", "كود نوع الضريبة (فاضي = V009)", "V009"),
    ("extra_discount", "خصم إضافي على الإيصال", ""),
    ("reference_uuid", "UUID الإيصال الأصلي (للمرتجع)", ""),
]

HEAD = PatternFill("solid", fgColor="1F4E78")


def write_template(path: str | Path, kind: str) -> None:
    columns = INVOICE_COLUMNS if kind == "invoices" else RECEIPT_COLUMNS
    wb = Workbook()
    ws = wb.active
    ws.title = kind
    ws.sheet_view.rightToLeft = True
    for col, (key, label, example) in enumerate(columns, 1):
        ws.cell(1, col, key).font = Font(color="FFFFFF", bold=True)
        ws.cell(1, col).fill = HEAD
        ws.cell(2, col, label).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(2, col).font = Font(bold=True)
        ws.cell(3, col, example if example != "" else None)
        ws.column_dimensions[ws.cell(1, col).column_letter].width = 22
    ws.row_dimensions[2].height = 45
    ws.freeze_panes = "A3"
    wb.save(path)


def read_rows(path: str | Path) -> list[dict]:
    wb = load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 3:
        return []
    keys = [str(k).strip() if k else "" for k in rows[0]]
    out = []
    for n, values in enumerate(rows[2:], start=3):
        if all(v is None or str(v).strip() == "" for v in values):
            continue
        row = {k: v for k, v in zip(keys, values) if k}
        row["_row"] = n
        out.append(row)
    return out


def write_report(path: str | Path, results: list[dict]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "النتيجة"
    ws.sheet_view.rightToLeft = True
    headers = ["الرقم", "الحالة", "UUID", "Long ID", "رقم الطلب", "الإجمالي", "الأخطاء"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(color="FFFFFF", bold=True)
        c.fill = HEAD
    colors = {"مقبول": "C6EFCE", "مرفوض": "FFC7CE", "جاهز (تجربة)": "FFEB9C"}
    for r in results:
        ws.append([r.get("id"), r.get("status"), r.get("uuid", ""), r.get("long_id", ""),
                   r.get("submission_id", ""), r.get("total", ""), r.get("error", "")])
        color = colors.get(r.get("status"))
        if color:
            ws.cell(ws.max_row, 2).fill = PatternFill("solid", fgColor=color)
    for letter, width in zip("ABCDEFG", (16, 14, 30, 30, 30, 14, 80)):
        ws.column_dimensions[letter].width = width
    wb.save(path)
