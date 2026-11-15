"""بناء الإيصال الإلكتروني (v1.2) وحساب الـ UUID بتاعه."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from decimal import Decimal

from .config import POS, Company
from .dates import to_eta_datetime
from .invoice import _s
from .money import dec, num, r5
from .serialize import serialize

PAYMENT_METHODS = {"C", "V", "CC", "VC", "VO", "PF", "GC", "O"}
BUYER_ID_THRESHOLD = Decimal("150000")


def build_item(row: dict) -> dict:
    qty = dec(row.get("quantity"))
    price = dec(row.get("unit_price"))
    if qty <= 0:
        raise ValueError("الكمية لازم تكون أكبر من صفر")
    item_code = _s(row, "item_code")
    if not item_code:
        raise ValueError("كود الصنف (item_code) فاضي")
    total_sale = r5(qty * price)
    disc = r5(dec(row.get("discount_amount")))
    net_sale = r5(total_sale - disc)
    vat_rate = dec(row.get("vat_rate"), "14")
    vat = r5(net_sale * vat_rate / 100)
    item = {
        "internalCode": _s(row, "internal_code", item_code),
        "description": _s(row, "description") or item_code,
        "itemType": _s(row, "item_type", "EGS").upper(),
        "itemCode": item_code,
        "unitType": _s(row, "unit_type", "EA"),
        "quantity": num(qty),
        "unitPrice": num(price),
        "netSale": num(net_sale),
        "totalSale": num(total_sale),
        "total": num(net_sale + vat),
    }
    if disc:
        item["commercialDiscountData"] = [{"amount": num(disc), "description": "خصم"}]
    item["taxableItems"] = [{
        "taxType": "T1",
        "amount": num(vat),
        "subType": _s(row, "vat_subtype", "V009"),
        "rate": num(vat_rate),
    }]
    return item


def compute_uuid(receipt: dict) -> str:
    """UUID = SHA-256 (hex) للتسلسل الموحّد للإيصال وحقل uuid فاضي."""
    copy = dict(receipt)
    copy["header"] = dict(receipt["header"], uuid="")
    return hashlib.sha256(serialize(copy).encode("utf-8")).hexdigest()


def build_receipt(company: Company, pos: POS, rows: list[dict], previous_uuid: str = "") -> dict:
    first = rows[0]
    receipt_type = _s(first, "receipt_type", "S").upper()
    if receipt_type not in {"S", "R"}:
        raise ValueError(f"نوع الإيصال لازم يكون S (بيع) أو R (مرتجع)، مش {receipt_type!r}")
    payment = _s(first, "payment_method", "C").upper()
    if payment not in PAYMENT_METHODS:
        raise ValueError(f"طريقة الدفع {payment!r} مش معروفة. المتاح: {', '.join(sorted(PAYMENT_METHODS))}")

    items = []
    for i, row in enumerate(rows, 1):
        try:
            items.append(build_item(row))
        except ValueError as exc:
            raise ValueError(f"سطر {i}: {exc}") from exc

    extra = dec(first.get("extra_discount"))
    total_sales = sum(dec(i["totalSale"]) for i in items)
    total_comm = sum(dec(d["amount"]) for i in items for d in i.get("commercialDiscountData", []))
    net_amount = sum(dec(i["netSale"]) for i in items)
    taxes: "OrderedDict[str, Decimal]" = OrderedDict()
    for i in items:
        for t in i["taxableItems"]:
            taxes[t["taxType"]] = taxes.get(t["taxType"], Decimal(0)) + dec(t["amount"])
    total_amount = sum(dec(i["total"]) for i in items) - extra

    header = {
        "dateTimeIssued": to_eta_datetime(first.get("date")),
        "receiptNumber": _s(first, "receipt_number"),
        "uuid": "",
        "previousUUID": previous_uuid,
    }
    if receipt_type == "R":
        ref = _s(first, "reference_uuid")
        if not ref:
            raise ValueError("إيصال المرتجع لازم يكون فيه UUID الإيصال الأصلي (reference_uuid)")
        header["referenceUUID"] = ref
    header.update({"currency": "EGP", "exchangeRate": 0.0})

    buyer = {"type": _s(first, "buyer_type", "P").upper()}
    buyer_id = _s(first, "buyer_id")
    if total_amount >= BUYER_ID_THRESHOLD and not buyer_id:
        raise ValueError("الإيصال بقيمة 150,000 أو أكتر لازم فيه رقم المشتري (buyer_id)")
    for key, col in (("id", "buyer_id"), ("name", "buyer_name"), ("mobileNumber", "buyer_mobile")):
        if _s(first, col):
            buyer[key] = _s(first, col)

    receipt = {
        "header": header,
        "documentType": {"receiptType": receipt_type, "typeVersion": "1.2"},
        "seller": {
            "rin": company.rin,
            "companyTradeName": company.name,
            "branchCode": pos.branch_code,
            "branchAddress": company.address.receipt_dict(),
            "deviceSerialNumber": pos.serial,
            "activityCode": company.activity_code,
        },
        "buyer": buyer,
        "itemData": items,
        "totalSales": num(total_sales),
        "totalCommercialDiscount": num(total_comm),
        "netAmount": num(net_amount),
        "feesAmount": 0.0,
        "totalAmount": num(total_amount),
        "taxTotals": [{"taxType": k, "amount": num(v)} for k, v in taxes.items()],
        "paymentMethod": payment,
    }
    if extra:
        receipt["extraReceiptDiscountData"] = [{"amount": num(extra), "description": "خصم إضافي"}]
    receipt["header"]["uuid"] = compute_uuid(receipt)
    return receipt
