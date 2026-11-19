"""منطق الرفع نفسه، مستخدم من الشاشة ومن سطر الأوامر."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import api
from .config import Company
from .excel_io import read_rows, write_report
from .invoice import _s, build_invoice, group_rows
from .receipt import build_receipt
from .signing import PfxSigner, Signer, TokenSigner, sign_document
from .state import ReceiptChain

OK_STATUSES = ("مقبول", "جاهز (تجربة)")
Log = Callable[[str], None]


@dataclass
class RunResult:
    out_dir: Path
    report: Path
    results: list[dict] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for r in self.results:
            c[r["status"]] = c.get(r["status"], 0) + 1
        return c

    @property
    def all_ok(self) -> bool:
        return all(r["status"] in OK_STATUSES for r in self.results)


def make_signer(company: Company, secret: str) -> Signer:
    """secret = الـ PIN بتاع التوكن، أو باسورد ملف الـ PFX لو pfx_path متحدد."""
    if company.pfx_path:
        return PfxSigner(company.pfx_path, secret)
    if not company.token_library:
        raise ValueError("token_library مش متحدد في إعدادات الشركة")
    return TokenSigner(company.token_library, secret, company.token_label)


def _out_dir(base: str | Path, kind: str, company: str) -> Path:
    d = Path(base) / company / f"{kind}-{datetime.now():%Y%m%d-%H%M%S}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _finish(out: Path, results: list[dict], log: Log) -> RunResult:
    report = out / "التقرير.xlsx"
    write_report(report, results)
    res = RunResult(out, report, results)
    log(" | ".join(f"{k}: {v}" for k, v in res.counts.items()))
    log(f"التقرير: {report}")
    return res


def run_invoices(company: Company, file: str | Path, out_base: str | Path, dry_run: bool,
                 signer_factory: Callable[[], Signer] | None = None, log: Log = print) -> RunResult:
    out = _out_dir(out_base, "invoices", company.key)
    results, docs = [], []
    for internal_id, rows in group_rows(read_rows(file), "internal_id").items():
        try:
            doc = build_invoice(company, rows)
            docs.append(doc)
            results.append({"id": internal_id, "status": "جاهز (تجربة)", "total": doc["totalAmount"]})
        except ValueError as exc:
            results.append({"id": internal_id, "status": "خطأ في البيانات",
                            "error": f"صف {rows[0]['_row']}: {exc}"})
    log(f"{len(docs)} فاتورة جاهزة، {len(results) - len(docs)} فيها أخطاء")
    if dry_run or not docs:
        for doc in docs:
            _save(out / f"{doc['internalID']}.json", doc)
        return _finish(out, results, log)

    if signer_factory is None:
        raise ValueError("مفيش وسيلة توقيع")
    log("بيتم التوقيع…")
    signer = signer_factory()
    try:
        for doc in docs:
            sign_document(doc, signer)
            _save(out / f"{doc['internalID']}.json", doc)
    finally:
        signer.close()

    log("بيتم تسجيل الدخول على المنظومة…")
    client = api.InvoiceClient(company)
    by_id = {r["id"]: r for r in results}
    for batch in _chunks(docs, api.BATCH_SIZE):
        log(f"بيتم رفع {len(batch)} فاتورة…")
        try:
            resp = client.submit(batch)
        except api.EtaError as exc:
            for d in batch:
                by_id[d["internalID"]].update(status="مرفوض", error=str(exc))
            continue
        _save(out / f"submission-{resp.get('submissionId')}.json", resp)
        for acc in resp.get("acceptedDocuments") or []:
            by_id[acc["internalId"]].update(status="تحت الفحص", uuid=acc["uuid"],
                                            long_id=acc.get("longId", ""),
                                            submission_id=resp.get("submissionId"))
        for rej in resp.get("rejectedDocuments") or []:
            by_id[rej["internalId"]].update(status="مرفوض", error=api.error_text(rej.get("error")))

        if resp.get("submissionId") and resp.get("acceptedDocuments"):
            log("مستني نتيجة الفحص…")
            summary = client.wait_for_validation(resp["submissionId"])
            for s in summary.get("documentSummary") or []:
                r = by_id.get(s.get("internalId"))
                if not r:
                    continue
                status = str(s.get("status", "")).lower()
                if status == "valid":
                    r["status"] = "مقبول"
                elif status == "invalid":
                    r["status"] = "مرفوض"
                    try:
                        r["error"] = api.validation_errors(client.document_details(s["uuid"]))
                    except Exception as exc:  # noqa: BLE001
                        r["error"] = f"مرفوض (تعذر جلب السبب: {exc})"
    return _finish(out, results, log)


def run_receipts(company: Company, file: str | Path, out_base: str | Path, dry_run: bool,
                 log: Log = print) -> RunResult:
    out = _out_dir(out_base, "receipts", company.key)
    chain = ReceiptChain(Path(out_base) / company.key / "receipt-chain.json")
    last: dict[str, str] = {}
    results, by_pos = [], {}
    for number, rows in group_rows(read_rows(file), "receipt_number").items():
        pos_key = _s(rows[0], "pos", "main")
        try:
            if pos_key not in company.pos:
                raise ValueError(f"نقطة البيع {pos_key!r} مش موجودة في الإعدادات")
            prev = last.get(pos_key, chain.last(company.key, pos_key))
            receipt = build_receipt(company, company.pos[pos_key], rows, prev)
            last[pos_key] = receipt["header"]["uuid"]
            by_pos.setdefault(pos_key, []).append(receipt)
            _save(out / f"{number}.json", receipt)
            results.append({"id": number, "status": "جاهز (تجربة)", "uuid": receipt["header"]["uuid"],
                            "total": receipt["totalAmount"]})
        except ValueError as exc:
            results.append({"id": number, "status": "خطأ في البيانات",
                            "error": f"صف {rows[0]['_row']}: {exc}"})
    log(f"{sum(map(len, by_pos.values()))} إيصال جاهز")
    if dry_run:
        return _finish(out, results, log)

    by_id = {r["id"]: r for r in results}
    for pos_key, receipts in by_pos.items():
        log(f"بيتم تسجيل دخول نقطة البيع {pos_key}…")
        client = api.ReceiptClient(company, company.pos[pos_key])
        for batch in _chunks(receipts, api.BATCH_SIZE):
            log(f"بيتم رفع {len(batch)} إيصال…")
            try:
                resp = client.submit(batch)
            except api.EtaError as exc:
                for rc in batch:
                    by_id[rc["header"]["receiptNumber"]].update(status="مرفوض", error=str(exc))
                continue
            _save(out / f"submission-{resp.get('submissionId')}.json", resp)
            for acc in resp.get("acceptedDocuments") or []:
                by_id[acc["receiptNumber"]].update(status="مقبول", submission_id=resp.get("submissionId"))
                chain.set(company.key, pos_key, acc["uuid"])
            for rej in resp.get("rejectedDocuments") or []:
                by_id[rej["receiptNumber"]].update(status="مرفوض", error=api.error_text(rej.get("error")))
    return _finish(out, results, log)
