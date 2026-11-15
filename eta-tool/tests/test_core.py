import base64
import datetime as dt
import hashlib

import pytest
from asn1crypto import cms
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from eta_tool.config import POS, Address, Company
from eta_tool.dates import CAIRO, to_eta_datetime
from eta_tool.invoice import build_invoice
from eta_tool.receipt import build_receipt, compute_uuid
from eta_tool.serialize import serialize, serialize_document
from eta_tool.signing import Signer, sign_document

COMPANY = Company(
    key="t", rin="100000000", name="Test Co", activity_code="4620",
    address=Address(governate="Cairo", regionCity="Nasr City", street="S", buildingNumber="1"),
    pos={"main": POS(serial="SN1", client_id="c", client_secret="s")},
)


def test_serialize_matches_eta_rules():
    data = {"a": "x", "b": {"c": 1.5}, "lines": [{"q": 2}, {"q": 3}]}
    assert serialize(data) == '"A""x""B""C""1.5""LINES""LINES""Q""2""LINES""Q""3"'


def test_serialize_skips_signatures():
    assert "SIGNATURES" not in serialize_document({"a": "1", "signatures": [{"v": "x"}]})


def row(**kw):
    base = {"internal_id": "INV1", "date": "2026-11-01", "receiver_type": "B", "receiver_id": "200000000",
            "receiver_name": "C", "receiver_governate": "Giza", "receiver_city": "Dokki",
            "receiver_street": "S", "receiver_building": "5", "item_code": "EG-1", "quantity": 2,
            "unit_price": 1000, "_row": 3}
    base.update(kw)
    return base


def test_invoice_totals_with_discount_and_wht():
    doc = build_invoice(COMPANY, [row(discount_amount=100, wht_rate=1), row(quantity=1, unit_price=500)])
    l1, l2 = doc["invoiceLines"]
    assert l1["salesTotal"] == 2000 and l1["netTotal"] == 1900
    assert l1["taxableItems"][0]["amount"] == 266  # 14% of 1900
    assert l1["taxableItems"][1] == {"taxType": "T4", "amount": 19.0, "subType": "W010", "rate": 1.0}
    assert l1["total"] == 1900 + 266 - 19
    assert l2["total"] == 570
    assert doc["totalSalesAmount"] == 2500 and doc["totalDiscountAmount"] == 100
    assert doc["netAmount"] == 2400
    assert doc["taxTotals"] == [{"taxType": "T1", "amount": 336.0}, {"taxType": "T4", "amount": 19.0}]
    assert doc["totalAmount"] == 2400 + 336 - 19


def test_invoice_validation_errors():
    with pytest.raises(ValueError, match="9"):
        build_invoice(COMPANY, [row(receiver_id="123")])
    with pytest.raises(ValueError, match="reference_uuid"):
        build_invoice(COMPANY, [row(document_type="C")])
    with pytest.raises(ValueError, match="قومي"):
        build_invoice(COMPANY, [row(receiver_type="P", receiver_id="", quantity=100)])


def test_dates_converted_to_utc():
    now = dt.datetime(2026, 11, 15, 12, 0, tzinfo=CAIRO)
    assert to_eta_datetime("2026-11-10", now) == "2026-11-10T08:00:00Z"
    assert to_eta_datetime("15/11/2026", now) == "2026-11-15T09:58:00Z"
    assert to_eta_datetime(dt.datetime(2026, 11, 14, 18, 30), now) == "2026-11-14T16:30:00Z"
    with pytest.raises(ValueError, match="المستقبل"):
        to_eta_datetime("2026-11-20", now)


def test_receipt_uuid_and_chain():
    r = {"receipt_number": "R1", "date": "2026-11-10 10:00", "item_code": "EG-1", "quantity": 1,
         "unit_price": 100, "_row": 3}
    first = build_receipt(COMPANY, COMPANY.pos["main"], [r])
    assert first["totalAmount"] == 114
    uuid = first["header"]["uuid"]
    assert len(uuid) == 64 and compute_uuid(first) == uuid
    second = build_receipt(COMPANY, COMPANY.pos["main"], [dict(r, receipt_number="R2")], uuid)
    assert second["header"]["previousUUID"] == uuid and second["header"]["uuid"] != uuid


class KeySigner(Signer):
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test")])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(self.key.public_key()).serial_number(1234)
                .not_valid_before(dt.datetime(2025, 1, 1)).not_valid_after(dt.datetime(2030, 1, 1))
                .sign(self.key, hashes.SHA256()))
        self.cert = cert
        self.certificate_der = cert.public_bytes(serialization.Encoding.DER)

    def sign_sha256_rsa(self, data):
        return self.key.sign(data, padding.PKCS1v15(), hashes.SHA256())


def test_cades_signature_verifies():
    signer = KeySigner()
    doc = sign_document(build_invoice(COMPANY, [row()]), signer)
    info = cms.ContentInfo.load(base64.b64decode(doc["signatures"][0]["value"]))
    sd = info["content"]
    assert sd["encap_content_info"]["content"].native is None  # detached
    si = sd["signer_infos"][0]
    attrs = {a["type"].native: a["values"][0] for a in si["signed_attrs"]}
    canonical = serialize_document(doc).encode()
    assert attrs["message_digest"].native == hashlib.sha256(canonical).digest()
    assert attrs["signing_certificate_v2"]["certs"][0]["cert_hash"].native == \
        hashlib.sha256(signer.certificate_der).digest()
    signed = b"\x31" + si["signed_attrs"].dump()[1:]  # الموقّع عليه هو SET مش [0]
    signer.cert.public_key().verify(si["signature"].native, signed,
                                    padding.PKCS1v15(), hashes.SHA256())
