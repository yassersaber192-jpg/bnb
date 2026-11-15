"""حفظ آخر UUID لكل نقطة بيع (الإيصالات لازم تتسلسل: كل إيصال فيه UUID اللي قبله)."""

from __future__ import annotations

import json
from pathlib import Path


class ReceiptChain:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def key(self, company: str, pos: str) -> str:
        return f"{company}/{pos}"

    def last(self, company: str, pos: str) -> str:
        return self.data.get(self.key(company, pos), "")

    def set(self, company: str, pos: str, uuid: str) -> None:
        self.data[self.key(company, pos)] = uuid
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
