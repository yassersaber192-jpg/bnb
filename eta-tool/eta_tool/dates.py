from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    CAIRO = ZoneInfo("Africa/Cairo")
except Exception:  # ويندوز من غير حزمة tzdata
    CAIRO = timezone(timedelta(hours=2))


def to_eta_datetime(value, now: datetime | None = None) -> str:
    """تحويل تاريخ/وقت (بتوقيت القاهرة) لصيغة المنظومة UTC: 2026-11-15T08:00:00Z.

    لو التاريخ من غير وقت: لو هو النهارده بناخد الوقت الحالي ناقص دقيقتين
    (المنظومة بترفض التاريخ اللي في المستقبل)، غير كده الساعة 10 الصبح.
    """
    now = now or datetime.now(CAIRO)
    if isinstance(value, str):
        text = value.strip()
        try:
            value = datetime.fromisoformat(text)
        except ValueError:
            try:
                value = datetime.strptime(text, "%d/%m/%Y")
                value = value.date()
            except ValueError as exc:
                raise ValueError(f"تاريخ غير مفهوم: {text!r} (استخدم 2026-11-15 أو 15/11/2026)") from exc
        else:
            if len(text) <= 10:
                value = value.date()
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=CAIRO)
        if dt.time() == time(0, 0) and not (isinstance(value, datetime) and value.tzinfo):
            value = dt.date()
    if isinstance(value, date) and not isinstance(value, datetime):
        if value == now.date():
            dt = now - timedelta(minutes=2)
        else:
            dt = datetime.combine(value, time(10, 0), tzinfo=CAIRO)
    if dt > now:
        raise ValueError(f"التاريخ {dt:%Y-%m-%d %H:%M} في المستقبل")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
