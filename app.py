"""Türkiye işletme dijital varlık analiz aracı (Streamlit)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from src.analyzer import analysis_table, dataframe_to_excel_bytes, summarize
from src.cities import CATEGORY_PRESETS, city_names
from src.enricher import enrich_businesses
from src.places_client import PlacesClientError, search_businesses

load_dotenv()

ROOT = Path(__file__).resolve().parent
DEMO_CSV = ROOT / "sample_data" / "demo_isletmeler.csv"

st.set_page_config(
    page_title="YVK Labs — İşletme Analizi",
    layout="wide",
)

st.title("İşletme dijital varlık analizi")
st.caption(
    "Şehir + kategori ile işletmeleri listeleyin; website ve sosyal medya varlığını analiz edin. "
    "Veri kaynağı: Google Places API (New)."
)

with st.sidebar:
    st.header("Arama")
    city = st.selectbox("Şehir", city_names(), index=city_names().index("İstanbul"))
    category = st.selectbox("Kategori", CATEGORY_PRESETS, index=0)
    custom_category = st.text_input("Özel kategori (opsiyonel)", placeholder="ör. vegan restoran")
    max_results = st.slider("Maks. işletme sayısı", min_value=20, max_value=120, value=40, step=20)
    do_enrich = st.checkbox("Website üzerinden sosyal medya tara", value=True)
    use_demo = st.checkbox(
        "Demo veri kullan (API anahtarı gerekmez)",
        value=not bool(os.getenv("GOOGLE_PLACES_API_KEY")),
    )
    run = st.button("Analizi başlat", type="primary", use_container_width=True)

    st.divider()
    st.markdown(
        "**Kurulum:** `.env.example` dosyasını `.env` yapıp "
        "`GOOGLE_PLACES_API_KEY` ekleyin. Places API (New) etkin olmalı."
    )


def load_demo() -> list[dict]:
    df = pd.read_csv(DEMO_CSV)
    return df.to_dict(orient="records")


if run:
    selected_category = custom_category.strip() or category
    with st.spinner("İşletmeler getiriliyor..."):
        try:
            if use_demo:
                businesses = load_demo()
                for row in businesses:
                    row["city"] = city
                    row["search_category"] = selected_category
            else:
                businesses = search_businesses(
                    city,
                    selected_category,
                    max_results=max_results,
                )
        except PlacesClientError as exc:
            st.error(str(exc))
            st.stop()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Beklenmeyen hata: {exc}")
            st.stop()

    if not businesses:
        st.warning("Sonuç bulunamadı. Farklı kategori veya şehir deneyin.")
        st.stop()

    if do_enrich:
        with st.spinner("Website ve sosyal medya taranıyor..."):
            businesses = enrich_businesses(businesses)
    else:
        for row in businesses:
            row.setdefault("has_website", bool(row.get("website")))
            row.setdefault("has_any_social", False)
            row.setdefault("social_count", 0)
            row.setdefault("website_reachable", False)

    df = pd.DataFrame(businesses)
    st.session_state["result_df"] = df
    st.session_state["meta"] = {
        "city": city,
        "category": selected_category,
        "demo": use_demo,
    }

if "result_df" not in st.session_state:
    st.info("Soldan şehir ve kategori seçip **Analizi başlat** düğmesine basın.")
    st.stop()

df: pd.DataFrame = st.session_state["result_df"]
meta = st.session_state.get("meta", {})
summary = summarize(df)

if meta.get("demo"):
    st.warning("Demo modundasınız. Canlı veri için `.env` içine API anahtarı ekleyin.")

st.subheader(
    f"{meta.get('city', '')} — {meta.get('category', '')} "
    f"({summary['total']} işletme)"
)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Toplam", summary["total"])
m2.metric("Website var", f"{summary['with_website']} (%{summary['website_pct']})")
m3.metric("Telefon var", f"{summary['with_phone']} (%{summary['phone_pct']})")
m4.metric("Sosyal medya var", f"{summary['with_any_social']} (%{summary['social_pct']})")
m5.metric(
    "Ort. puan",
    summary["avg_rating"] if summary["avg_rating"] is not None else "—",
)

left, right = st.columns(2)

with left:
    maturity = summary["digital_maturity"]
    maturity_df = pd.DataFrame(
        {
            "segment": [
                "Dijital güçlü (web + sosyal)",
                "Sadece website",
                "Sadece sosyal",
                "Dijital zayıf",
            ],
            "adet": [
                maturity.get("dijital_guclu", 0),
                maturity.get("sadece_website", 0),
                maturity.get("sadece_sosyal", 0),
                maturity.get("dijital_zayif", 0),
            ],
        }
    )
    fig_maturity = px.pie(
        maturity_df,
        names="segment",
        values="adet",
        title="Dijital olgunluk dağılımı",
        hole=0.35,
    )
    st.plotly_chart(fig_maturity, use_container_width=True)

with right:
    platform_cov = summary["platform_coverage"]
    if platform_cov:
        plat_df = pd.DataFrame(
            [
                {"platform": k, "oran_%": v["pct"], "adet": v["count"]}
                for k, v in platform_cov.items()
            ]
        )
        fig_plat = px.bar(
            plat_df,
            x="platform",
            y="oran_%",
            text="adet",
            title="Platform kapsama oranı (%)",
        )
        fig_plat.update_traces(textposition="outside")
        st.plotly_chart(fig_plat, use_container_width=True)
    else:
        st.info("Sosyal medya tarama kapalı veya veri yok.")

view = analysis_table(df)
st.dataframe(view, use_container_width=True, height=420)

csv_bytes = view.to_csv(index=False).encode("utf-8-sig")
xlsx_bytes = dataframe_to_excel_bytes(df)

c1, c2 = st.columns(2)
c1.download_button(
    "CSV indir",
    data=csv_bytes,
    file_name=f"{meta.get('city', 'sehir')}_{meta.get('category', 'kategori')}.csv",
    mime="text/csv",
    use_container_width=True,
)
c2.download_button(
    "Excel indir (liste + özet)",
    data=xlsx_bytes,
    file_name=f"{meta.get('city', 'sehir')}_{meta.get('category', 'kategori')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
