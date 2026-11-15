"""توقيع الفواتير بصيغة CAdES-BES (CMS detached) زي ما المنظومة بتطلب.

فيه نوعين موقّع:
- TokenSigner: التوكن الحقيقي (USB) عن طريق مكتبة PKCS#11 بتاعة الشركة المصدّرة.
- PfxSigner: ملف شهادة .pfx — للتجربة على البيئة التجريبية بس.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone

from asn1crypto import algos, cms, tsp, x509

from .serialize import serialize_document


class Signer:
    certificate_der: bytes

    def sign_sha256_rsa(self, data: bytes) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:
        pass


def build_cades_bes(content: bytes, signer: Signer, signing_time: datetime | None = None) -> str:
    cert = x509.Certificate.load(signer.certificate_der)
    signing_time = signing_time or datetime.now(timezone.utc)

    ess_cert = tsp.ESSCertIDv2({
        "hash_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
        "cert_hash": hashlib.sha256(signer.certificate_der).digest(),
        "issuer_serial": tsp.IssuerSerial({
            "issuer": [x509.GeneralName({"directory_name": cert.issuer})],
            "serial_number": cert.serial_number,
        }),
    })
    signed_attrs = cms.CMSAttributes([
        cms.CMSAttribute({"type": "content_type", "values": ["data"]}),
        cms.CMSAttribute({"type": "signing_time", "values": [cms.Time({"utc_time": signing_time})]}),
        cms.CMSAttribute({"type": "message_digest", "values": [hashlib.sha256(content).digest()]}),
        cms.CMSAttribute({
            "type": "signing_certificate_v2",
            "values": [tsp.SigningCertificateV2({"certs": [ess_cert]})],
        }),
    ])
    signature = signer.sign_sha256_rsa(signed_attrs.dump())

    signer_info = cms.SignerInfo({
        "version": "v1",
        "sid": cms.SignerIdentifier({
            "issuer_and_serial_number": cms.IssuerAndSerialNumber({
                "issuer": cert.issuer,
                "serial_number": cert.serial_number,
            })
        }),
        "digest_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
        "signed_attrs": signed_attrs,
        "signature_algorithm": algos.SignedDigestAlgorithm({"algorithm": "sha256_rsa"}),
        "signature": signature,
    })
    signed_data = cms.SignedData({
        "version": "v1",
        "digest_algorithms": [algos.DigestAlgorithm({"algorithm": "sha256"})],
        "encap_content_info": {"content_type": "data"},  # detached: من غير المحتوى
        "certificates": [cert],
        "signer_infos": [signer_info],
    })
    info = cms.ContentInfo({"content_type": "signed_data", "content": signed_data})
    return base64.b64encode(info.dump()).decode("ascii")


def sign_document(document: dict, signer: Signer) -> dict:
    canonical = serialize_document(document).encode("utf-8")
    value = build_cades_bes(canonical, signer)
    document["signatures"] = [{"signatureType": "I", "value": value}]
    return document


class PfxSigner(Signer):
    def __init__(self, path: str, password: str):
        from cryptography.hazmat.primitives.serialization import Encoding, pkcs12

        with open(path, "rb") as fh:
            key, cert, _ = pkcs12.load_key_and_certificates(fh.read(), password.encode() or None)
        self._key = key
        self.certificate_der = cert.public_bytes(Encoding.DER)

    def sign_sha256_rsa(self, data: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        return self._key.sign(data, padding.PKCS1v15(), hashes.SHA256())


class TokenSigner(Signer):
    """التوكن عن طريق PKCS#11.

    أمثلة لمسار المكتبة على ويندوز:
    - Egypt Trust (ePass2003):  C:\\Windows\\System32\\eps2003csp11.dll
    - MCDR / SafeNet eToken:    C:\\Windows\\System32\\eTPKCS11.dll
    """

    def __init__(self, library: str, pin: str, token_label: str = ""):
        import pkcs11
        from pkcs11 import Attribute, ObjectClass

        lib = pkcs11.lib(library)
        if token_label:
            token = lib.get_token(token_label=token_label)
        else:
            slots = lib.get_slots(token_present=True)
            if not slots:
                raise RuntimeError("مفيش توكن متوصّل بالجهاز")
            token = slots[0].get_token()
        self._session = token.open(user_pin=pin)

        keys = list(self._session.get_objects({Attribute.CLASS: ObjectClass.PRIVATE_KEY}))
        certs = list(self._session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}))
        if not keys or not certs:
            raise RuntimeError("التوكن مفيهوش مفتاح أو شهادة")
        self._key = keys[0]
        key_id = self._key[Attribute.ID]
        cert = next((c for c in certs if c[Attribute.ID] == key_id), certs[0])
        self.certificate_der = bytes(cert[Attribute.VALUE])

    def sign_sha256_rsa(self, data: bytes) -> bytes:
        from pkcs11 import Mechanism

        return bytes(self._key.sign(data, mechanism=Mechanism.SHA256_RSA_PKCS))

    def close(self) -> None:
        self._session.close()
