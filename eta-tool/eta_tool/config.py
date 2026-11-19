"""إعدادات الشركات (ممكن أكتر من شركة/عميل في نفس الملف)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ENVIRONMENTS = {
    "preprod": {
        "id": "https://id.preprod.eta.gov.eg",
        "api": "https://api.preprod.invoicing.eta.gov.eg",
    },
    "prod": {
        "id": "https://id.eta.gov.eg",
        "api": "https://api.invoicing.eta.gov.eg",
    },
}


EXAMPLE_CONFIG = {
    "companies": {
        "sample": {
            "rin": "100000000",
            "name": "شركة المثال للتجارة",
            "activity_code": "4620",
            "environment": "preprod",
            "address": {
                "branchID": "0",
                "country": "EG",
                "governate": "Cairo",
                "regionCity": "Nasr City",
                "street": "شارع مكرم عبيد",
                "buildingNumber": "10"
            },
            "client_id": "ضع-هنا-Client-ID-الخاص-بالنظام",
            "client_secret": "ضع-هنا-Client-Secret",
            "token_library": "C:\\Windows\\System32\\eps2003csp11.dll",
            "token_label": "",
            "pos": {
                "main": {
                    "serial": "رقم-سيريال-نقطة-البيع",
                    "client_id": "Client-ID-الخاص-بنقطة-البيع",
                    "client_secret": "Client-Secret-الخاص-بنقطة-البيع",
                    "os_version": "windows",
                    "model_framework": "1",
                    "pre_shared_key": "",
                    "branch_code": "0"
                }
            }
        }
    }
}


@dataclass
class Address:
    governate: str
    regionCity: str
    street: str
    buildingNumber: str
    country: str = "EG"
    branchID: str = "0"

    def invoice_dict(self) -> dict:
        return {
            "branchID": self.branchID,
            "country": self.country,
            "governate": self.governate,
            "regionCity": self.regionCity,
            "street": self.street,
            "buildingNumber": self.buildingNumber,
        }

    def receipt_dict(self) -> dict:
        return {
            "country": self.country,
            "governate": self.governate,
            "regionCity": self.regionCity,
            "street": self.street,
            "buildingNumber": self.buildingNumber,
        }


@dataclass
class POS:
    serial: str
    client_id: str
    client_secret: str
    os_version: str = "windows"
    model_framework: str = "1"
    pre_shared_key: str = ""
    branch_code: str = "0"


@dataclass
class Company:
    key: str
    rin: str
    name: str
    activity_code: str
    address: Address
    environment: str = "preprod"
    client_id: str = ""
    client_secret: str = ""
    token_library: str = ""
    token_label: str = ""
    pfx_path: str = ""
    pos: dict[str, POS] = field(default_factory=dict)

    @property
    def urls(self) -> dict:
        if self.environment not in ENVIRONMENTS:
            raise ValueError(f"environment لازم يكون preprod أو prod، مش {self.environment!r}")
        return ENVIRONMENTS[self.environment]


def load_companies(path: str | Path) -> dict[str, Company]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    companies = {}
    for key, c in raw.get("companies", {}).items():
        try:
            pos = {k: POS(**v) for k, v in c.get("pos", {}).items()}
            companies[key] = Company(
                key=key,
                rin=str(c["rin"]),
                name=c["name"],
                activity_code=str(c["activity_code"]),
                address=Address(**{k: str(v) for k, v in c["address"].items()}),
                environment=c.get("environment", "preprod"),
                client_id=c.get("client_id", ""),
                client_secret=c.get("client_secret", ""),
                token_library=c.get("token_library", ""),
                token_label=c.get("token_label", ""),
                pfx_path=c.get("pfx_path", ""),
                pos=pos,
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"إعدادات الشركة {key!r} ناقصة أو غلط: {exc}") from exc
    return companies


def get_company(path: str | Path, key: str) -> Company:
    companies = load_companies(path)
    if key not in companies:
        raise ValueError(f"الشركة {key!r} مش موجودة. الموجود: {', '.join(companies) or 'لا شيء'}")
    return companies[key]
