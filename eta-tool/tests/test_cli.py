"""تشغيل كامل للأوامر مع API وهمي (من غير اتصال حقيقي بالمنظومة)."""

import datetime as dt
import json

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from openpyxl import load_workbook

from eta_tool import __main__ as cli
from eta_tool import api
from eta_tool.excel_io import write_template


class Resp:
    def __init__(self, data, status=200):
        self.status_code, self._data, self.text = status, data, json.dumps(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def make_pfx(path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "T")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(7).not_valid_before(dt.datetime(2025, 1, 1))
            .not_valid_after(dt.datetime(2030, 1, 1)).sign(key, hashes.SHA256()))
    path.write_bytes(pkcs12.serialize_key_and_certificates(b"t", key, cert, None,
                                                          BestAvailableEncryption(b"pw")))


def setup(tmp_path, kind, extra_rows):
    cfg = json.loads(open("config.example.json", encoding="utf-8").read())
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    xlsx = tmp_path / f"{kind}.xlsx"
    write_template(xlsx, kind)
    wb = load_workbook(xlsx)
    ws = wb.active
    example = [c.value for c in ws[3]]
    for changes in extra_rows:
        r = list(example)
        for i, v in changes.items():
            r[i] = v
        ws.append(r)
    wb.save(xlsx)
    return xlsx


def report(tmp_path):
    f = next(tmp_path.glob("out/sample/*/التقرير.xlsx"))
    return list(load_workbook(f).active.iter_rows(min_row=2, values_only=True))


def test_invoice_submission(tmp_path, monkeypatch):
    xlsx = setup(tmp_path, "invoices", [{0: "INV-002"}])
    pfx = tmp_path / "t.pfx"
    make_pfx(pfx)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: "pw")
    sent = {}

    def post(url, **kw):
        if url.endswith("/connect/token"):
            assert kw["data"]["scope"] == "InvoicingAPI"
            return Resp({"access_token": "tok"})
        sent["docs"] = kw["json"]["documents"]
        return Resp({"submissionId": "SUB1",
                     "acceptedDocuments": [{"uuid": "U1", "longId": "L1", "internalId": "INV-001"},
                                           {"uuid": "U2", "longId": "L2", "internalId": "INV-002"}],
                     "rejectedDocuments": []}, 202)

    def get(url, **kw):
        if "documentSubmissions" in url:
            return Resp({"overallStatus": "Invalid", "documentSummary": [
                {"uuid": "U1", "internalId": "INV-001", "status": "Valid"},
                {"uuid": "U2", "internalId": "INV-002", "status": "Invalid"}]})
        return Resp({"validationResults": {"validationSteps": [
            {"name": "Core", "status": "Invalid",
             "error": {"innerError": [{"propertyPath": "itemCode", "error": "Item code not registered"}]}}]}})

    monkeypatch.setattr(api.requests, "post", post)
    monkeypatch.setattr(api.requests, "get", get)
    code = cli.main(["invoices", str(xlsx), "--company", "sample", "--config", str(tmp_path / "config.json"),
                     "--out", str(tmp_path / "out"), "--pfx", str(pfx)])
    assert code == 1
    assert len(sent["docs"]) == 2 and sent["docs"][0]["signatures"][0]["signatureType"] == "I"
    rows = report(tmp_path)
    assert rows[0][:4] == ("INV-001", "مقبول", "U1", "L1")
    assert rows[1][1] == "مرفوض" and "Item code not registered" in rows[1][6]


def test_receipt_submission_updates_chain(tmp_path, monkeypatch):
    xlsx = setup(tmp_path, "receipts", [{0: "R-0002"}])
    sent = {}

    def post(url, **kw):
        if url.endswith("/connect/token"):
            assert kw["headers"]["posserial"]
            return Resp({"access_token": "tok"})
        sent["receipts"] = kw["json"]["receipts"]
        return Resp({"submissionId": "S", "acceptedDocuments": [
            {"uuid": r["header"]["uuid"], "receiptNumber": r["header"]["receiptNumber"]}
            for r in kw["json"]["receipts"]], "rejectedDocuments": []}, 202)

    monkeypatch.setattr(api.requests, "post", post)
    args = ["receipts", str(xlsx), "--company", "sample", "--config", str(tmp_path / "config.json"),
            "--out", str(tmp_path / "out")]
    assert cli.main(args) == 0
    r1, r2 = sent["receipts"]
    assert r2["header"]["previousUUID"] == r1["header"]["uuid"]
    chain = json.loads((tmp_path / "out/sample/receipt-chain.json").read_text())
    assert chain["sample/main"] == r2["header"]["uuid"]
