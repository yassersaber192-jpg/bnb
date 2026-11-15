"""التسلسل الموحّد (canonical serialization) اللي بتطلبه المنظومة.

بيُستخدم في حاجتين:
- الفواتير: النص الناتج هو اللي بيتوقّع بالتوكن.
- الإيصالات: الـ UUID = SHA-256 للنص الناتج.

القاعدة (من الـ SDK الرسمي):
- لكل خاصية في object: "اسم_الخاصية_بالحروف_الكبيرة" ثم قيمتها مُسلسلة.
- لو القيمة array: الاسم مرة، وبعدين لكل عنصر: الاسم تاني ثم العنصر.
- القيم البسيطة بتتحط بين علامتي تنصيص زي ما هي مكتوبة في الـ JSON.
"""

from __future__ import annotations

import json


def _primitive(value) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif value is None:
        text = ""
    else:
        # الأرقام بنفس الشكل اللي json.dumps بيكتبها بيه في الطلب المرسَل.
        text = json.dumps(value)
    return '"' + text + '"'


def serialize(value) -> str:
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            name = '"' + key.upper() + '"'
            if isinstance(item, list):
                out.append(name)
                for element in item:
                    out.append(name)
                    out.append(serialize(element))
            else:
                out.append(name)
                out.append(serialize(item))
        return "".join(out)
    if isinstance(value, list):
        return "".join(serialize(v) for v in value)
    return _primitive(value)


def serialize_document(document: dict) -> str:
    """تسلسل مستند من غير حقل التوقيعات."""
    doc = {k: v for k, v in document.items() if k != "signatures"}
    return serialize(doc)
