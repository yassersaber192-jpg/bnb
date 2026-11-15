"""سطر الأوامر. من غير أوامر بيفتح الشاشة.

  python -m eta_tool                       ← الشاشة
  python -m eta_tool template invoices قالب.xlsx
  python -m eta_tool invoices فواتير.xlsx --company sample [--dry-run] [--pfx شهادة.pfx]
  python -m eta_tool receipts ايصالات.xlsx --company sample [--dry-run]
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import api
from .config import get_company
from .excel_io import write_template
from .runner import make_signer, run_invoices, run_receipts


def cmd_template(args) -> int:
    write_template(args.output, args.kind)
    print(f"اتعمل القالب: {args.output}")
    return 0


def cmd_invoices(args) -> int:
    company = get_company(args.config, args.company)
    if args.pfx:
        company.pfx_path = args.pfx
    prompt = "باسورد ملف الـ PFX: " if company.pfx_path else "الـ PIN بتاع التوكن: "
    res = run_invoices(company, args.file, args.out, args.dry_run,
                       lambda: make_signer(company, getpass.getpass(prompt)))
    return 0 if res.all_ok else 1


def cmd_receipts(args) -> int:
    company = get_company(args.config, args.company)
    res = run_receipts(company, args.file, args.out, args.dry_run)
    return 0 if res.all_ok else 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .gui import main as gui_main
        gui_main()
        return 0
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
