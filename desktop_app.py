"""YVK Labs — İşletme dijital varlık analizi (masaüstü)."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import customtkinter as ctk
import pandas as pd
from dotenv import load_dotenv
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from src.analyzer import analysis_table, dataframe_to_excel_bytes, summarize
from src.cities import CATEGORY_PRESETS, city_names
from src.districts import district_names
from src.enricher import enrich_businesses
from src.osm_client import OsmClientError, search_businesses_osm
from src.places_client import PlacesClientError, search_businesses

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv()

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

TABLE_COLUMNS = (
    ("name", "İşletme", 160),
    ("city", "Şehir", 80),
    ("address", "Adres", 200),
    ("phone", "Telefon", 110),
    ("website_status", "Website", 70),
    ("website", "Website URL", 150),
    ("instagram_status", "Instagram", 75),
    ("instagram_url", "IG URL", 140),
    ("instagram_location", "IG Konum", 110),
    ("instagram_phone", "IG Tel", 100),
    ("rating", "Puan", 50),
    ("review_count", "Yorum", 55),
)


class BusinessAnalyzerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("YVK Labs — İşletme Analizi")
        self.geometry("1280x800")
        self.minsize(1060, 680)

        self._df: pd.DataFrame | None = None
        self._worker: threading.Thread | None = None
        self._chart_canvas: FigureCanvasTkAgg | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=300, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(
            sidebar,
            text="YVK Labs",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(padx=20, pady=(24, 4), anchor="w")
        ctk.CTkLabel(
            sidebar,
            text="Kaynak: OpenStreetMap (API key yok)",
            font=ctk.CTkFont(size=13),
            text_color=("gray30", "gray70"),
        ).pack(padx=20, pady=(0, 20), anchor="w")

        ctk.CTkLabel(sidebar, text="Şehir").pack(padx=20, anchor="w")
        cities = city_names()
        self.city_var = ctk.StringVar(value="İstanbul" if "İstanbul" in cities else cities[0])
        self.city_menu = ctk.CTkOptionMenu(sidebar, values=cities, variable=self.city_var)
        self.city_menu.pack(padx=20, pady=(4, 12), fill="x")

        ctk.CTkLabel(sidebar, text="İlçe").pack(padx=20, anchor="w")
        self.district_var = ctk.StringVar(value="Tümü")
        self.district_menu = ctk.CTkOptionMenu(
            sidebar, values=["Tümü"], variable=self.district_var
        )
        self.district_menu.pack(padx=20, pady=(4, 12), fill="x")
        self.city_var.trace_add("write", self._on_city_change)
        self._on_city_change()

        ctk.CTkLabel(sidebar, text="Kategori").pack(padx=20, anchor="w")
        self.category_var = ctk.StringVar(value=CATEGORY_PRESETS[0])
        self.category_menu = ctk.CTkOptionMenu(
            sidebar, values=CATEGORY_PRESETS, variable=self.category_var
        )
        self.category_menu.pack(padx=20, pady=(4, 12), fill="x")

        ctk.CTkLabel(sidebar, text="Özel kategori (opsiyonel)").pack(padx=20, anchor="w")
        self.custom_category = ctk.CTkEntry(
            sidebar, placeholder_text="ör. vegan restoran"
        )
        self.custom_category.pack(padx=20, pady=(4, 12), fill="x")

        ctk.CTkLabel(sidebar, text="Maks. işletme sayısı").pack(padx=20, anchor="w")
        self.max_results = ctk.CTkSlider(
            sidebar, from_=20, to=120, number_of_steps=5
        )
        self.max_results.set(40)
        self.max_results.pack(padx=20, pady=(4, 4), fill="x")
        self.max_label = ctk.CTkLabel(sidebar, text="40")
        self.max_label.pack(padx=20, anchor="w")
        self.max_results.configure(command=self._on_max_change)

        self.enrich_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            sidebar,
            text="Website var mı? (kontrol et)",
            variable=self.enrich_var,
        ).pack(padx=20, pady=(14, 8), anchor="w")

        self.instagram_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            sidebar,
            text="Instagram var mı? (ara + konum)",
            variable=self.instagram_var,
        ).pack(padx=20, pady=(0, 12), anchor="w")

        has_key = bool(os.getenv("GOOGLE_PLACES_API_KEY", "").strip())
        self.use_google_var = ctk.BooleanVar(value=False)
        if has_key:
            ctk.CTkCheckBox(
                sidebar,
                text="Google Maps kullan (API key var)",
                variable=self.use_google_var,
            ).pack(padx=20, pady=(0, 8), anchor="w")
        else:
            ctk.CTkLabel(
                sidebar,
                text="API anahtarı gerekmez.\nVeri: OpenStreetMap haritası.",
                font=ctk.CTkFont(size=11),
                text_color=("gray40", "gray60"),
                justify="left",
            ).pack(padx=20, pady=(0, 8), anchor="w")

        self.run_btn = ctk.CTkButton(
            sidebar,
            text="Analizi başlat",
            height=40,
            command=self._start_analysis,
        )
        self.run_btn.pack(padx=20, pady=(4, 10), fill="x")

        self.status_label = ctk.CTkLabel(
            sidebar,
            text="Hazır.",
            wraplength=250,
            justify="left",
            text_color=("gray30", "gray70"),
        )
        self.status_label.pack(padx=20, pady=(8, 20), anchor="w")

        ctk.CTkLabel(
            sidebar,
            text="Veri: OpenStreetMap\nWebsite + Instagram kontrolü\nayrıca yapılır.",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            justify="left",
        ).pack(side="bottom", padx=20, pady=20, anchor="w")

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=16, pady=16)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        self.metrics_frame = ctk.CTkFrame(main)
        self.metrics_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        for i in range(5):
            self.metrics_frame.grid_columnconfigure(i, weight=1)

        self.metric_labels: list[ctk.CTkLabel] = []
        titles = ["Toplam", "Website Var", "Telefon", "Instagram Var", "Ort. puan"]
        for i, title in enumerate(titles):
            card = ctk.CTkFrame(self.metrics_frame)
            card.grid(row=0, column=i, padx=6, pady=8, sticky="ew")
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12)).pack(pady=(8, 0))
            value = ctk.CTkLabel(card, text="—", font=ctk.CTkFont(size=20, weight="bold"))
            value.pack(pady=(0, 8))
            self.metric_labels.append(value)

        self.chart_frame = ctk.CTkFrame(main)
        self.chart_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.chart_host = tk.Frame(self.chart_frame, bg="#dbdbdb")
        self.chart_host.pack(fill="both", expand=True, padx=8, pady=8)

        table_wrap = ctk.CTkFrame(main)
        table_wrap.grid(row=2, column=0, sticky="nsew")
        table_wrap.grid_columnconfigure(0, weight=1)
        table_wrap.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Biz.Treeview",
            rowheight=28,
            font=("Segoe UI", 10),
            borderwidth=0,
        )
        style.configure("Biz.Treeview.Heading", font=("Segoe UI Semibold", 10))

        self.tree = ttk.Treeview(
            table_wrap,
            columns=[c[0] for c in TABLE_COLUMNS],
            show="headings",
            style="Biz.Treeview",
        )
        for key, title, width in TABLE_COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=50, stretch=True)

        y_scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        actions = ctk.CTkFrame(main, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.csv_btn = ctk.CTkButton(
            actions, text="CSV kaydet", state="disabled", command=self._export_csv
        )
        self.csv_btn.pack(side="left", padx=(0, 8))
        self.xlsx_btn = ctk.CTkButton(
            actions, text="Excel kaydet", state="disabled", command=self._export_xlsx
        )
        self.xlsx_btn.pack(side="left")

    def _on_city_change(self, *_args: object) -> None:
        districts = district_names(self.city_var.get())
        self.district_menu.configure(values=districts)
        if self.district_var.get() not in districts:
            self.district_var.set(districts[0])

    def _on_max_change(self, value: float) -> None:
        self.max_label.configure(text=str(int(round(value))))

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self.run_btn.configure(state="disabled" if busy else "normal")
        if status:
            self.status_label.configure(text=status)

    def _start_analysis(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._set_busy(True, "İşletmeler getiriliyor...")
        self._worker = threading.Thread(target=self._run_analysis, daemon=True)
        self._worker.start()

    def _run_analysis(self) -> None:
        city = self.city_var.get()
        district = self.district_var.get()
        custom = self.custom_category.get().strip()
        category = custom or self.category_var.get()
        max_results = int(round(self.max_results.get()))
        do_enrich = self.enrich_var.get()
        scan_instagram = self.instagram_var.get()
        use_google = bool(
            getattr(self, "use_google_var", None)
            and self.use_google_var.get()
            and os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
        )
        source_label = "Google Maps" if use_google else "OpenStreetMap"

        try:
            self.after(
                0,
                lambda: self.status_label.configure(
                    text=f"{source_label}: {city} / {category}..."
                ),
            )
            if use_google:
                businesses = search_businesses(
                    city,
                    category,
                    district=district,
                    max_results=max_results,
                )
            else:
                businesses = search_businesses_osm(
                    city,
                    category,
                    district=district,
                    max_results=max_results,
                )

            if not businesses:
                self.after(
                    0,
                    lambda: self._on_error(
                        f"{source_label} üzerinde sonuç bulunamadı.\n"
                        "Farklı kategori veya şehir deneyin.\n\n"
                        "Not: OpenStreetMap her işletmeyi içermeyebilir;"
                        " yaygın kategoriler (restoran, kafe, eczane…) daha iyi sonuç verir."
                    ),
                )
                return

            if do_enrich or scan_instagram:
                self.after(
                    0,
                    lambda: self.status_label.configure(
                        text="Website / Instagram varlık kontrolü..."
                    ),
                )
                businesses = enrich_businesses(
                    businesses,
                    scan_website=do_enrich,
                    scan_instagram=scan_instagram,
                )
            else:
                for row in businesses:
                    row["website_status"] = "var" if row.get("has_website") else "yok"
                    row["instagram_status"] = (
                        "var" if row.get("has_instagram") else "kontrol_edilmedi"
                    )

            df = pd.DataFrame(businesses)
            self.after(
                0,
                lambda: self._on_success(df, city, category, source_label),
            )
        except (PlacesClientError, OsmClientError) as exc:
            self.after(0, lambda: self._on_error(str(exc)))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._on_error(f"Beklenmeyen hata: {exc}"))

    def _on_error(self, message: str) -> None:
        self._set_busy(False, "Hata oluştu.")
        messagebox.showerror("Hata", message)

    def _on_success(
        self, df: pd.DataFrame, city: str, category: str, source_label: str
    ) -> None:
        self._df = df
        summary = summarize(df)
        self._update_metrics(summary)
        self._update_table(df)
        self._update_charts(summary)
        district = self.district_var.get()
        self._set_busy(
            False,
            f"{source_label}: {city} / {district} / {category} — {summary['total']} işletme.",
        )
        self.csv_btn.configure(state="normal")
        self.xlsx_btn.configure(state="normal")

    def _update_metrics(self, summary: dict[str, Any]) -> None:
        ig = summary.get("platform_coverage", {}).get("instagram", {})
        ig_count = ig.get("count", summary.get("with_any_social", 0))
        ig_pct = ig.get("pct", summary.get("social_pct", 0))
        values = [
            str(summary["total"]),
            f"{summary['with_website']} (%{summary['website_pct']})",
            f"{summary['with_phone']} (%{summary['phone_pct']})",
            f"{ig_count} (%{ig_pct})",
            str(summary["avg_rating"] if summary["avg_rating"] is not None else "—"),
        ]
        for label, value in zip(self.metric_labels, values, strict=True):
            label.configure(text=value)

    def _cell_value(self, key: str, raw: Any) -> str:
        if key in ("has_website", "has_instagram", "has_any_social") or key.startswith("has_"):
            return "Var" if bool(raw) else "Yok"
        if key in ("website_status", "instagram_status"):
            text = str(raw or "").strip().lower()
            if text in {"var", "true", "1"}:
                return "Var"
            if text in {"yok", "false", "0"}:
                return "Yok"
            if text == "kontrol_edilmedi":
                return "—"
            return str(raw or "—")
        if pd.isna(raw):
            return ""
        return str(raw)

    def _update_table(self, df: pd.DataFrame) -> None:
        self.tree.delete(*self.tree.get_children())
        view = analysis_table(df)
        if "website_status" not in view.columns:
            view["website_status"] = view.get("has_website", False).map(
                lambda x: "var" if bool(x) else "yok"
            )
        if "instagram_status" not in view.columns:
            view["instagram_status"] = view.get("has_instagram", False).map(
                lambda x: "var" if bool(x) else "yok"
            )
        for _, row in view.iterrows():
            values = []
            for key, _, _ in TABLE_COLUMNS:
                raw = row.get(key, "")
                values.append(self._cell_value(key, raw))
            self.tree.insert("", "end", values=values)

    def _update_charts(self, summary: dict[str, Any]) -> None:
        if self._chart_canvas is not None:
            self._chart_canvas.get_tk_widget().destroy()
            self._chart_canvas = None

        fig = Figure(figsize=(10.5, 2.8), dpi=100)
        fig.patch.set_facecolor("#f4f4f4")

        ax1 = fig.add_subplot(121)
        maturity = summary.get("digital_maturity") or {}
        labels = [
            "Web + sosyal",
            "Sadece web",
            "Sadece sosyal",
            "Zayıf",
        ]
        sizes = [
            maturity.get("dijital_guclu", 0),
            maturity.get("sadece_website", 0),
            maturity.get("sadece_sosyal", 0),
            maturity.get("dijital_zayif", 0),
        ]
        if sum(sizes) == 0:
            ax1.text(0.5, 0.5, "Veri yok", ha="center", va="center")
            ax1.axis("off")
        else:
            ax1.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90)
            ax1.set_title("Dijital olgunluk")

        ax2 = fig.add_subplot(122)
        coverage = summary.get("platform_coverage") or {}
        platforms = list(coverage.keys())
        pcts = [coverage[p]["pct"] for p in platforms]
        if platforms:
            ax2.bar(platforms, pcts, color="#2B7BBB")
            ax2.set_ylim(0, 100)
            ax2.set_ylabel("%")
            ax2.set_title("Platform kapsama")
            ax2.tick_params(axis="x", rotation=30)
        else:
            ax2.text(0.5, 0.5, "Sosyal veri yok", ha="center", va="center")
            ax2.axis("off")

        fig.tight_layout()
        self._chart_canvas = FigureCanvasTkAgg(fig, master=self.chart_host)
        self._chart_canvas.draw()
        self._chart_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _export_csv(self) -> None:
        if self._df is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="isletme_analizi.csv",
        )
        if not path:
            return
        analysis_table(self._df).to_csv(path, index=False, encoding="utf-8-sig")
        messagebox.showinfo("Kaydedildi", f"CSV kaydedildi:\n{path}")

    def _export_xlsx(self) -> None:
        if self._df is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="isletme_analizi.xlsx",
        )
        if not path:
            return
        Path(path).write_bytes(dataframe_to_excel_bytes(self._df))
        messagebox.showinfo("Kaydedildi", f"Excel kaydedildi:\n{path}")

    def _on_close(self) -> None:
        self.destroy()


def main() -> None:
    app = BusinessAnalyzerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
