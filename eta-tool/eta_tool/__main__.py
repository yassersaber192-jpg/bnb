"""واجهة الأوامر.

أمثلة:
  python -m eta_tool template invoices قالب_فواتير.xlsx
  python -m eta_tool invoices فواتير.xlsx --company sample --dry-run
  python -m eta_tool invoices فواتير.xlsx --company sample
  python -m eta_tool receipts ايصالات.xlsx --company sample
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import datetime
from pathlib import Path

from . import api
from .config import get_company
from .excel_io import read_rows, write_report, write_template
from .invoice import _s, build_invoice, group_rows
from .receipt import build_receipt
from .signing import PfxSigner, TokenSigner, sign_document
from .state import ReceiptChain


def _out_dir(base: str, kind: str, company: str) -> Path:
    d = Path(base) / company / f"{kind}-{datetime.now():%Y%m%d-%H%M%S}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _finish(out: Path, results: list[dict]) -> int:
    report = out / "التقرير.xlsx"
    write_report(report, results)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("\n" + " | ".join(f"{k}: {v}" for k, v in counts.items()))
    print(f"التقرير: {report}")
    return 0 if all(r["status"] in ("مقبول", "جاهز (تجربة)") for r in results) else 1


def cmd_template(args) -> int:
    write_template(args.output, args.kind)
    print(f"اتعمل القالب: {args.output}")
    return 0


def cmd_invoices(args) -> int:
    company = get_company(args.config, args.company)
    out = _out_dir(args.out, "invoices", company.key)
    results, docs = [], []
    for internal_id, rows in group_rows(read_rows(args.file), "internal_id").items():
        try:
            doc = build_invoice(company, rows)
            docs.append(doc)
            results.append({"id": internal_id, "status": "جاهز (تجربة)", "total": doc["totalAmount"]})
        except ValueError as exc:
            results.append({"id": internal_id, "status": "خطأ في البيانات",
                            "error": f"صف {rows[0]['_row']}: {exc}"})
    print(f"{len(docs)} فاتورة جاهزة، {len(results) - len(docs)} فيها أخطاء")
    if args.dry_run or not docs:
        for doc in docs:
            _save(out / f"{doc['internalID']}.json", doc)
        return _finish(out, results)

    if args.pfx:
        signer = PfxSigner(args.pfx, getpass.getpass("باسورد ملف الـ PFX: "))
    else:
        if not company.token_library:
            raise SystemExit("token_library مش متحدد في إعدادات الشركة")
        signer = TokenSigner(company.token_library, getpass.getpass("الـ PIN بتاع التوكن: "),
                             company.token_label)
    try:
        for doc in docs:
            sign_document(doc, signer)
            _save(out / f"{doc['internalID']}.json", doc)
    finally:
        signer.close()

    client = api.InvoiceClient(company)
    by_id = {r["id"]: r for r in results}
    for batch in _chunks(docs, api.BATCH_SIZE):
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

        # الفحص النهائي بيحصل بعد الاستلام بثواني
        if resp.get("submissionId") and resp.get("acceptedDocuments"):
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
    return _finish(out, results)


def cmd_receipts(args) -> int:
    company = get_company(args.config, args.company)
    out = _out_dir(args.out, "receipts", company.key)
    chain = ReceiptChain(Path(args.out) / company.key / "receipt-chain.json")
    last = {}
    results, by_pos = [], {}
    for number, rows in group_rows(read_rows(args.file), "receipt_number").items():
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
            results.append({"id": number, "status": "خطأ في البيانات", "error": f"صف {rows[0]['_row']}: {exc}"})
    print(f"{sum(map(len, by_pos.values()))} إيصال جاهز")
    if args.dry_run:
        return _finish(out, results)

    by_id = {r["id"]: r for r in results}
    for pos_key, receipts in by_pos.items():
        client = api.ReceiptClient(company, company.pos[pos_key])
        for batch in _chunks(receipts, api.BATCH_SIZE):
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
    return _finish(out, results)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(prog="eta_tool", description="رفع الفواتير والإيصالات على منظومة الضرائب")
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("template", help="عمل قالب Excel فاضي")
    t.add_argument("kind", choices=["invoices", "receipts"])
    t.add_argument("output")
    t.set_defaults(func=cmd_template)

    for name, func, help_ in (("invoices", cmd_invoices, "رفع فواتير"), ("receipts", cmd_receipts, "رفع إيصالات")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("file", help="ملف الـ Excel")
        s.add_argument("--company", required=True, help="اسم الشركة في ملف الإعدادات")
        s.add_argument("--config", default="config.json")
        s.add_argument("--out", default="output", help="فولدر النتايج")
        s.add_argument("--dry-run", action="store_true", help="مراجعة وحساب بس من غير رفع")
        if name == "invoices":
            s.add_argument("--pfx", help="توقيع بملف PFX بدل التوكن (للبيئة التجريبية)")
        s.set_defaults(func=func)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, api.EtaError, RuntimeError, FileNotFoundError) as exc:
        print(f"خطأ: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
