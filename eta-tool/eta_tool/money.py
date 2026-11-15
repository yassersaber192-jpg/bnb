"""حسابات الفلوس بـ Decimal وتقريب لـ 5 أرقام عشرية زي ما المنظومة بتقبل."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

Q = Decimal("0.00001")


def dec(value, default: str = "0") -> Decimal:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return Decimal(default)
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"قيمة رقمية غير صحيحة: {value!r}") from exc


def r5(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Q, rounding=ROUND_HALF_UP)


def num(value: Decimal) -> float:
    """تحويل لرقم JSON مقرّب لـ 5 أرقام."""
    return float(r5(value))
