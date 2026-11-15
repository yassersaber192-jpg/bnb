"""الاتصال بـ API المنظومة."""

from __future__ import annotations

import time

import requests

from .config import POS, Company

TIMEOUT = 60
BATCH_SIZE = 50  # المنظومة بتحدد حجم كل طلب (عدد وحجم بالـ MB)، 50 رقم آمن


class EtaError(RuntimeError):
    pass


def _token(url: str, data: dict, headers: dict | None = None) -> str:
    resp = requests.post(url + "/connect/token", data=data, headers=headers or {}, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise EtaError(f"فشل تسجيل الدخول ({resp.status_code}): {resp.text[:500]}")
    return resp.json()["access_token"]


class InvoiceClient:
    def __init__(self, company: Company):
        if not company.client_id or not company.client_secret:
            raise EtaError("client_id و client_secret ناقصين في إعدادات الشركة")
        self.api = company.urls["api"]
        self.access_token = _token(company.urls["id"], {
            "grant_type": "client_credentials",
            "client_id": company.client_id,
            "client_secret": company.client_secret,
            "scope": "InvoicingAPI",
        })

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def submit(self, documents: list[dict]) -> dict:
        resp = requests.post(f"{self.api}/api/v1/documentsubmissions",
                             json={"documents": documents}, headers=self._headers(), timeout=TIMEOUT)
        if resp.status_code not in (200, 202):
            raise EtaError(f"المنظومة رفضت الطلب ({resp.status_code}): {resp.text[:1000]}")
        return resp.json()

    def submission(self, submission_id: str) -> dict:
        resp = requests.get(f"{self.api}/api/v1.0/documentSubmissions/{submission_id}",
                            params={"PageNo": 1, "PageSize": 100}, headers=self._headers(), timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def document_details(self, uuid: str) -> dict:
        resp = requests.get(f"{self.api}/api/v1.0/documents/{uuid}/details",
                            headers=self._headers(), timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def wait_for_validation(self, submission_id: str, attempts: int = 10, delay: float = 3) -> dict:
        result = {}
        for _ in range(attempts):
            result = self.submission(submission_id)
            if result.get("overallStatus", "").lower() != "inprogress":
                break
            time.sleep(delay)
        return result


class ReceiptClient:
    def __init__(self, company: Company, pos: POS):
        self.api = company.urls["api"]
        self.access_token = _token(company.urls["id"], {
            "grant_type": "client_credentials",
            "client_id": pos.client_id,
            "client_secret": pos.client_secret,
        }, headers={
            "posserial": pos.serial,
            "pososversion": pos.os_version,
            "posmodelframework": pos.model_framework,
            "presharedkey": pos.pre_shared_key,
        })

    def submit(self, receipts: list[dict]) -> dict:
        resp = requests.post(f"{self.api}/api/v1/receiptsubmissions",
                             json={"receipts": receipts},
                             headers={"Authorization": f"Bearer {self.access_token}",
                                      "Content-Type": "application/json"},
                             timeout=TIMEOUT)
        if resp.status_code not in (200, 202):
            raise EtaError(f"المنظومة رفضت الطلب ({resp.status_code}): {resp.text[:1000]}")
        return resp.json()


def validation_errors(details: dict) -> str:
    """استخراج أسباب رفض المستند بعد الفحص."""
    msgs = []
    for step in (details.get("validationResults") or {}).get("validationSteps") or []:
        if str(step.get("status", "")).lower() == "invalid":
            err = step.get("error") or {}
            inner = err.get("innerError") or []
            if inner:
                msgs.extend(f"{e.get('propertyPath', '')}: {e.get('error', '')}" for e in inner)
            else:
                msgs.append(f"{step.get('name', '')}: {err.get('error', '')}")
    return " | ".join(msgs)


def error_text(error) -> str:
    if not error:
        return ""
    if isinstance(error, str):
        return error
    parts = [str(error.get("message", ""))]
    for d in error.get("details") or []:
        parts.append(f"{d.get('target') or d.get('propertyPath', '')}: {d.get('message', '')}")
    return " | ".join(p for p in parts if p)
