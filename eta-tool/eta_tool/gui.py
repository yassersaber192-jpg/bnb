"""الشاشة الرئيسية للأداة (Tkinter — جزء من Python، مش محتاجة تسطيب)."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import (BooleanVar, StringVar, Text, Tk, filedialog, messagebox, simpledialog, ttk)

from . import __version__
from .config import EXAMPLE_CONFIG, load_companies
from .excel_io import write_template
from .runner import make_signer, run_invoices, run_receipts

STATUS_TAGS = {
    "مقبول": "ok", "جاهز (تجربة)": "ready", "تحت الفحص": "ready",
    "مرفوض": "bad", "خطأ في البيانات": "bad",
}


def base_dir() -> Path:
    """الفولدر اللي جنب البرنامج (أو الـ exe) — فيه الإعدادات والنتايج."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.base = base_dir()
        self.settings_file = self.base / "gui_settings.json"
        self.queue: queue.Queue = queue.Queue()
        self.companies = {}
        self.last_result = None
        self.busy = False

        settings = self._load_settings()
        self.config_path = StringVar(value=settings.get("config", str(self.base / "config.json")))
        self.company = StringVar(value=settings.get("company", ""))
        self.kind = StringVar(value=settings.get("kind", "invoices"))
        self.excel = StringVar(value=settings.get("excel", ""))
        self.env_text = StringVar()
        self.status = StringVar(value="جاهز")
        self.show_ok = BooleanVar(value=True)

        root.title(f"رفع الفواتير والإيصالات الإلكترونية  v{__version__}")
        root.geometry("1050x680")
        root.minsize(850, 560)
        self._build()
        self.reload_companies()
        self.root.after(100, self._poll)

    # ---------- بناء الشاشة ----------
    def _build(self) -> None:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TButton", padding=(14, 8))
        style.configure("Env.TLabel", font=("Segoe UI", 10, "bold"))

        top = ttk.LabelFrame(self.root, text=" الإعدادات ", padding=10)
        top.pack(fill="x", padx=10, pady=(10, 5))
        top.columnconfigure(1, weight=1)

        # كل صف: العنوان على اليمين، والأزرار على الشمال
        ttk.Label(top, text="ملف الإعدادات:").grid(row=0, column=3, sticky="e", padx=4)
        ttk.Entry(top, textvariable=self.config_path, justify="left").grid(row=0, column=1, columnspan=2, sticky="ew", padx=4)
        bar = ttk.Frame(top)
        bar.grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="اختيار…", command=self.pick_config).pack(side="left", padx=2)
        ttk.Button(bar, text="تعديل", command=self.edit_config).pack(side="left", padx=2)
        ttk.Button(bar, text="تحديث", command=self.reload_companies).pack(side="left", padx=2)

        ttk.Label(top, text="الشركة:").grid(row=1, column=3, sticky="e", padx=4, pady=6)
        self.company_box = ttk.Combobox(top, textvariable=self.company, state="readonly", justify="right")
        self.company_box.grid(row=1, column=2, sticky="ew", padx=4, pady=6)
        self.company_box.bind("<<ComboboxSelected>>", lambda e: self._update_env())
        self.env_label = ttk.Label(top, textvariable=self.env_text, style="Env.TLabel")
        self.env_label.grid(row=1, column=1, sticky="e", padx=8)

        ttk.Label(top, text="النوع:").grid(row=2, column=3, sticky="e", padx=4)
        kinds = ttk.Frame(top)
        kinds.grid(row=2, column=2, sticky="e")
        ttk.Radiobutton(kinds, text="إيصالات", value="receipts", variable=self.kind).pack(side="right", padx=8)
        ttk.Radiobutton(kinds, text="فواتير", value="invoices", variable=self.kind).pack(side="right", padx=8)

        ttk.Label(top, text="ملف Excel:").grid(row=3, column=3, sticky="e", padx=4, pady=6)
        ttk.Entry(top, textvariable=self.excel, justify="left").grid(row=3, column=1, columnspan=2, sticky="ew", padx=4, pady=6)
        bar2 = ttk.Frame(top)
        bar2.grid(row=3, column=0, sticky="w")
        ttk.Button(bar2, text="اختيار…", command=self.pick_excel).pack(side="left", padx=2)
        ttk.Button(bar2, text="فتح", command=lambda: self._open_if(self.excel.get())).pack(side="left", padx=2)
        ttk.Button(bar2, text="قالب فاضي…", command=self.make_template).pack(side="left", padx=2)

        actions = ttk.Frame(self.root, padding=(10, 5))
        actions.pack(fill="x")
        self.btn_submit = ttk.Button(actions, text="⬆  رفع على المنظومة", style="Big.TButton",
                                     command=lambda: self.start(dry_run=False))
        self.btn_submit.pack(side="right", padx=4)
        self.btn_review = ttk.Button(actions, text="✓  مراجعة بدون رفع", style="Big.TButton",
                                     command=lambda: self.start(dry_run=True))
        self.btn_review.pack(side="right", padx=4)
        ttk.Button(actions, text="فولدر النتايج", command=self.open_output).pack(side="left", padx=4)
        self.btn_report = ttk.Button(actions, text="فتح التقرير", command=self.open_report, state="disabled")
        self.btn_report.pack(side="left", padx=4)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=160)
        self.progress.pack(side="left", padx=10)

        mid = ttk.PanedWindow(self.root, orient="vertical")
        mid.pack(fill="both", expand=True, padx=10, pady=5)

        table_frame = ttk.LabelFrame(mid, text=" النتيجة (دبل كليك على أي سطر لعرض التفاصيل) ", padding=5)
        cols = ("error", "uuid", "total", "status", "id")
        self.table = ttk.Treeview(table_frame, columns=cols, show="headings", height=12)
        for col, title, width, anchor in (
            ("id", "الرقم", 110, "e"), ("status", "الحالة", 130, "center"),
            ("total", "الإجمالي", 100, "e"), ("uuid", "UUID", 230, "w"), ("error", "الأخطاء", 420, "e"),
        ):
            self.table.heading(col, text=title)
            self.table.column(col, width=width, anchor=anchor, stretch=col in ("error", "uuid"))
        self.table.tag_configure("ok", background="#d9f2dc")
        self.table.tag_configure("ready", background="#fff4cc")
        self.table.tag_configure("bad", background="#f9d6d5")
        sb = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=sb.set)
        sb.pack(side="left", fill="y")
        self.table.pack(side="right", fill="both", expand=True)
        self.table.bind("<Double-1>", self.show_row)
        mid.add(table_frame, weight=3)

        log_frame = ttk.LabelFrame(mid, text=" السجل ", padding=5)
        self.log_box = Text(log_frame, height=7, wrap="word", state="disabled", font=("Segoe UI", 9))
        self.log_box.tag_configure("rtl", justify="right")
        self.log_box.pack(fill="both", expand=True)
        mid.add(log_frame, weight=1)

        ttk.Label(self.root, textvariable=self.status, anchor="e", padding=(10, 3),
                  relief="sunken").pack(fill="x", side="bottom")

    # ---------- إعدادات محفوظة ----------
    def _load_settings(self) -> dict:
        try:
            return json.loads(self.settings_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save_settings(self) -> None:
        data = {"config": self.config_path.get(), "company": self.company.get(),
                "kind": self.kind.get(), "excel": self.excel.get()}
        try:
            self.settings_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    # ---------- الإعدادات والشركات ----------
    def reload_companies(self) -> None:
        path = Path(self.config_path.get())
        if not path.exists():
            self.companies = {}
            self.company_box["values"] = []
            self.env_text.set("")
            self.log(f"ملف الإعدادات مش موجود: {path}. دوس «تعديل» عشان يتعمل ملف مثال وتملاه.")
            return
        try:
            self.companies = load_companies(path)
        except Exception as exc:  # noqa: BLE001
            self.companies = {}
            self.company_box["values"] = []
            messagebox.showerror("خطأ في ملف الإعدادات", str(exc))
            return
        names = list(self.companies)
        self.company_box["values"] = names
        if self.company.get() not in names:
            self.company.set(names[0] if names else "")
        self._update_env()
        self.log(f"اتحمّل {len(names)} شركة من {path.name}")

    def _update_env(self) -> None:
        c = self.companies.get(self.company.get())
        if not c:
            self.env_text.set("")
            return
        if c.environment == "prod":
            self.env_text.set("●  المنظومة الفعلية")
            self.env_label.configure(foreground="#b00020")
        else:
            self.env_text.set("●  البيئة التجريبية")
            self.env_label.configure(foreground="#1a7f37")
        self.status.set(f"{c.name} — رقم التسجيل {c.rin}")

    def pick_config(self) -> None:
        f = filedialog.askopenfilename(title="اختيار ملف الإعدادات", filetypes=[("JSON", "*.json")])
        if f:
            self.config_path.set(f)
            self.reload_companies()

    def edit_config(self) -> None:
        path = Path(self.config_path.get())
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(EXAMPLE_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("ملف الإعدادات",
                                "اتعمل ملف إعدادات مثال. املاه ببيانات الشركة واحفظه، وبعدين دوس «تحديث».")
        if sys.platform.startswith("win"):
            subprocess.Popen(["notepad.exe", str(path)])
        else:
            open_path(path)

    # ---------- الملفات ----------
    def pick_excel(self) -> None:
        f = filedialog.askopenfilename(title="اختيار ملف Excel", filetypes=[("Excel", "*.xlsx *.xlsm")])
        if f:
            self.excel.set(f)

    def make_template(self) -> None:
        kind = self.kind.get()
        name = "قالب_الفواتير.xlsx" if kind == "invoices" else "قالب_الإيصالات.xlsx"
        f = filedialog.asksaveasfilename(title="حفظ القالب", initialfile=name, defaultextension=".xlsx",
                                         filetypes=[("Excel", "*.xlsx")])
        if not f:
            return
        write_template(f, kind)
        self.excel.set(f)
        self.log(f"اتعمل القالب: {f}")
        if messagebox.askyesno("القالب", "اتعمل القالب. تفتحه دلوقتي؟"):
            open_path(Path(f))

    def _open_if(self, path: str) -> None:
        if path and Path(path).exists():
            open_path(Path(path))

    def output_dir(self) -> Path:
        return Path(self.config_path.get()).resolve().parent / "output"

    def open_output(self) -> None:
        d = self.output_dir()
        d.mkdir(parents=True, exist_ok=True)
        open_path(d)

    def open_report(self) -> None:
        if self.last_result:
            open_path(self.last_result.report)

    # ---------- التشغيل ----------
    def start(self, dry_run: bool) -> None:
        if self.busy:
            return
        company = self.companies.get(self.company.get())
        if not company:
            messagebox.showwarning("تنبيه", "اختار الشركة الأول (أو املا ملف الإعدادات).")
            return
        excel = self.excel.get()
        if not excel or not Path(excel).exists():
            messagebox.showwarning("تنبيه", "اختار ملف الـ Excel الأول.")
            return
        kind = self.kind.get()
        signer_factory = None
        if not dry_run:
            what = "الفواتير" if kind == "invoices" else "الإيصالات"
            where = "المنظومة الفعلية" if company.environment == "prod" else "البيئة التجريبية"
            if not messagebox.askyesno("تأكيد الرفع",
                                       f"هيتم رفع {what} من الملف ده على {where}\nللشركة: {company.name}\n\nمتأكد؟",
                                       icon="warning" if company.environment == "prod" else "question"):
                return
            if kind == "invoices":
                label = "باسورد ملف الـ PFX:" if company.pfx_path else "اكتب الـ PIN بتاع التوكن:"
                secret = simpledialog.askstring("التوقيع", label, show="*", parent=self.root)
                if secret is None:
                    return
                signer_factory = lambda: make_signer(company, secret)  # noqa: E731

        self._save_settings()
        self.table.delete(*self.table.get_children())
        self.last_result = None
        self.btn_report.configure(state="disabled")
        self._set_busy(True)
        self.log("—" * 30)
        self.log("مراجعة الملف…" if dry_run else "بدء الرفع…")
        out = self.output_dir()

        def work():
            try:
                log = lambda m: self.queue.put(("log", m))  # noqa: E731
                if kind == "invoices":
                    res = run_invoices(company, excel, out, dry_run, signer_factory, log)
                else:
                    res = run_receipts(company, excel, out, dry_run, log)
                self.queue.put(("done", res))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", (exc, traceback.format_exc())))

        threading.Thread(target=work, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn_submit.configure(state=state)
        self.btn_review.configure(state=state)
        if busy:
            self.progress.start(12)
            self.status.set("شغّال… استنى لحد ما يخلص")
        else:
            self.progress.stop()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "done":
                    self._set_busy(False)
                    self.show_results(payload)
                elif kind == "error":
                    self._set_busy(False)
                    exc, tb = payload
                    self.log(f"خطأ: {exc}")
                    self.status.set("حصل خطأ")
                    messagebox.showerror("خطأ", str(exc))
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def show_results(self, res) -> None:
        self.last_result = res
        self.btn_report.configure(state="normal")
        for r in res.results:
            total = r.get("total", "")
            if isinstance(total, (int, float)):
                total = f"{total:,.2f}"
            self.table.insert("", "end", values=(r.get("error", ""), r.get("uuid", ""), total,
                                                 r["status"], r["id"]),
                              tags=(STATUS_TAGS.get(r["status"], ""),))
        summary = " | ".join(f"{k}: {v}" for k, v in res.counts.items())
        self.status.set(summary)
        if not res.all_ok:
            messagebox.showwarning("النتيجة", f"{summary}\n\nالسطور اللي باللون الأحمر فيها مشاكل — دبل كليك لعرض السبب.")

    def show_row(self, _event=None) -> None:
        sel = self.table.selection()
        if not sel:
            return
        error, uuid, total, status, ident = self.table.item(sel[0], "values")
        text = f"الرقم: {ident}\nالحالة: {status}\nالإجمالي: {total}"
        if uuid:
            text += f"\nUUID: {uuid}"
        if error:
            text += f"\n\nالأخطاء:\n" + error.replace(" | ", "\n")
        if uuid:
            self.root.clipboard_clear()
            self.root.clipboard_append(uuid)
            text += "\n\n(الـ UUID اتنسخ)"
        messagebox.showinfo("تفاصيل", text)

    def log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n", "rtl")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


def main() -> None:
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
