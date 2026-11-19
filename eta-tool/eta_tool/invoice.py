"""بناء مستند الفاتورة (v1.0) من صفوف Excel وحساب الإجماليات."""

from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal

from .config import Company
from .dates import to_eta_datetime
from .money import dec, num, r5

DOC_TYPES = {"I", "C", "D"}  # فاتورة / إشعار دائن / إشعار مدين
RECEIVER_TYPES = {"B", "P", "F"}  # شركة / شخص طبيعي / أجنبي
NATIONAL_ID_THRESHOLD = Decimal("50000")


def _s(row: dict, key: str, default: str = "") -> str:
    value = row.get(key)
    if value is None:
        return default
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip() or default


def build_line(row: dict) -> dict:
    qty = dec(row.get("quantity"))
    unit = dec(row.get("unit_price"))
    if qty <= 0:
        raise ValueError("الكمية لازم تكون أكبر من صفر")
    if unit < 0:
        raise ValueError("سعر الوحدة مينفعش يكون بالسالب")
    item_code = _s(row, "item_code")
    if not item_code:
        raise ValueError("كود الصنف (item_code) فاضي")

    sales_total = r5(qty * unit)
    disc_rate = dec(row.get("discount_rate"))
    disc_amount = dec(row.get("discount_amount"))
    if disc_amount == 0 and disc_rate:
        disc_amount = r5(sales_total * disc_rate / 100)
    net_total = r5(sales_total - disc_amount)
    items_discount = r5(dec(row.get("items_discount")))

    taxes = []
    vat_rate = dec(row.get("vat_rate"), "14")
    vat_amount = r5(net_total * vat_rate / 100)
    taxes.append({
        "taxType": "T1",
        "amount": num(vat_amount),
        "subType": _s(row, "vat_subtype", "V009"),
        "rate": num(vat_rate),
    })
    wht_rate = dec(row.get("wht_rate"))
    wht_amount = Decimal(0)
    if wht_rate:
        wht_amount = r5((net_total - items_discount) * wht_rate / 100)
        taxes.append({
            "taxType": "T4",
            "amount": num(wht_amount),
            "subType": _s(row, "wht_subtype", "W010"),
            "rate": num(wht_rate),
        })

    total = r5(net_total + vat_amount - wht_amount - items_discount)
    return {
        "description": _s(row, "description") or item_code,
        "itemType": _s(row, "item_type", "EGS").upper(),
        "itemCode": item_code,
        "unitType": _s(row, "unit_type", "EA"),
        "quantity": num(qty),
        "internalCode": _s(row, "internal_code", item_code),
        "salesTotal": num(sales_total),
        "total": num(total),
        "valueDifference": 0.0,
        "totalTaxableFees": 0.0,
        "netTotal": num(net_total),
        "itemsDiscount": num(items_discount),
        "unitValue": {"currencySold": "EGP", "amountEGP": num(unit)},
        "discount": {"rate": num(disc_rate), "amount": num(disc_amount)},
        "taxableItems": taxes,
    }


def build_invoice(company: Company, rows: list[dict]) -> dict:
    first = rows[0]
    internal_id = _s(first, "internal_id")
    doc_type = _s(first, "document_type", "I").upper()
    if doc_type not in DOC_TYPES:
        raise ValueError(f"نوع المستند لازم يكون I أو C أو D، مش {doc_type!r}")
    receiver_type = _s(first, "receiver_type", "B").upper()
    if receiver_type not in RECEIVER_TYPES:
        raise ValueError(f"نوع العميل لازم يكون B أو P أو F، مش {receiver_type!r}")

    lines = []
    for i, row in enumerate(rows, 1):
        try:
            lines.append(build_line(row))
        except ValueError as exc:
            raise ValueError(f"سطر {i}: {exc}") from exc

    total_sales = sum(dec(l["salesTotal"]) for l in lines)
    total_disc = sum(dec(l["discount"]["amount"]) for l in lines)
    net_amount = sum(dec(l["netTotal"]) for l in lines)
    items_disc = sum(dec(l["itemsDiscount"]) for l in lines)
    extra_disc = dec(first.get("extra_discount"))
    tax_totals: "OrderedDict[str, Decimal]" = OrderedDict()
    for l in lines:
        for t in l["taxableItems"]:
            tax_totals[t["taxType"]] = tax_totals.get(t["taxType"], Decimal(0)) + dec(t["amount"])
    total_amount = sum(dec(l["total"]) for l in lines) - extra_disc

    receiver_id = _s(first, "receiver_id")
    if receiver_type == "B" and not (receiver_id.isdigit() and len(receiver_id) == 9):
        raise ValueError(f"رقم التسجيل الضريبي للعميل لازم يكون 9 أرقام: {receiver_id!r}")
    if receiver_type == "P" and total_amount >= NATIONAL_ID_THRESHOLD and len(receiver_id) != 14:
        raise ValueError("الفاتورة لشخص طبيعي بقيمة 50,000 أو أكتر لازم فيها رقم قومي 14 رقم")

    receiver = {
        "address": {
            "country": _s(first, "receiver_country", "EG"),
            "governate": _s(first, "receiver_governate"),
            "regionCity": _s(first, "receiver_city"),
            "street": _s(first, "receiver_street"),
            "buildingNumber": _s(first, "receiver_building"),
        },
        "type": receiver_type,
        "id": receiver_id,
        "name": _s(first, "receiver_name"),
    }
    if receiver_type == "B" and not all(receiver["address"].values()):
        raise ValueError("عنوان العميل (شركة) لازم يكون كامل: المحافظة، المدينة، الشارع، رقم المبنى")

    doc = {
        "issuer": {
            "address": company.address.invoice_dict(),
            "type": "B",
            "id": company.rin,
            "name": company.name,
        },
        "receiver": receiver,
        "documentType": doc_type,
        "documentTypeVersion": "1.0",
        "dateTimeIssued": to_eta_datetime(first.get("date")),
        "taxpayerActivityCode": company.activity_code,
        "internalID": internal_id,
        "invoiceLines": lines,
        "totalDiscountAmount": num(total_disc),
        "totalSalesAmount": num(total_sales),
        "netAmount": num(net_amount),
        "taxTotals": [{"taxType": k, "amount": num(v)} for k, v in tax_totals.items()],
        "totalAmount": num(total_amount),
        "extraDiscountAmount": num(extra_disc),
        "totalItemsDiscountAmount": num(items_disc),
    }
    if doc_type in {"C", "D"}:
        refs = [u.strip() for u in _s(first, "reference_uuid").split(",") if u.strip()]
        if not refs:
            raise ValueError("الإشعار الدائن/المدين لازم يكون فيه UUID الفاتورة الأصلية (reference_uuid)")
        doc["references"] = refs
    return doc


def group_rows(rows: list[dict], key: str) -> "OrderedDict[str, list[dict]]":
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for row in rows:
        k = _s(row, key)
        if not k:
            raise ValueError(f"فيه سطر من غير {key}")
        groups.setdefault(k, []).append(row)
    return groups
