"""Dashboard interativo do JEPA-Spillover (Streamlit).

Explora o espaço latente, o ranking de priorização e as métricas do modelo.

Uso:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jepa_spillover.config import Config  # noqa: E402

st.set_page_config(page_title="JEPA-Spillover", page_icon="🧬", layout="wide")

cfg = Config.load()
PROC = cfg.resolve("data_processed")
METRICS = cfg.resolve("metrics")
RANKINGS = cfg.resolve("rankings")
FIGURES = cfg.resolve("figures")


@st.cache_data(show_spinner=False)
def load_dataset():
    p = PROC / "dataset.parquet"
    return pd.read_parquet(p) if p.exists() else None


@st.cache_data(show_spinner=False)
def load_latent():
    p = PROC / "latent_2d.parquet"
    return pd.read_parquet(p) if p.exists() else None


@st.cache_data(show_spinner=False)
def load_ranking():
    p = RANKINGS / "virus_priority_ranking.csv"
    return pd.read_csv(p) if p.exists() else None


@st.cache_data(show_spinner=False)
def load_metrics():
    p = METRICS / "finetune_metrics.json"
    return json.loads(p.read_text()) if p.exists() else None


st.title("🧬 JEPA-Spillover")
st.caption(
    "Aprendizado preditivo em espaço latente para vigilância genômica de vírus "
    "com potencial zoonótico — Instituto Aggeu Magalhães / Fiocruz"
)

df = load_dataset()
if df is None:
    st.warning(
        "Nenhum dataset encontrado. Rode o pipeline primeiro:\n\n"
        "```bash\nmake pipeline\n# ou\npython -m jepa_spillover.cli all\n```"
    )
    st.stop()

# ----- Métricas resumo -----
c1, c2, c3, c4 = st.columns(4)
c1.metric("Vírus", f"{len(df):,}")
c2.metric("Famílias", df["family"].nunique())
if "spillover_label" in df:
    c3.metric("Zoonóticos (rótulo)", int(df["spillover_label"].sum()))
metrics = load_metrics()
if metrics and metrics.get("cv", {}).get("auroc") == metrics.get("cv", {}).get("auroc"):
    c4.metric("AUROC (CV)", f"{metrics['cv']['auroc']:.3f}")

tab_latent, tab_rank, tab_metrics, tab_data = st.tabs(
    ["Espaço latente", "Ranking de priorização", "Métricas", "Dados"]
)

# ----- Espaço latente -----
with tab_latent:
    latent = load_latent()
    if latent is None:
        st.info("Execute `make evaluate` para gerar a projeção 2D do espaço latente.")
    else:
        color_by = st.radio("Colorir por", ["family", "spillover_label"], horizontal=True)
        try:
            import plotly.express as px

            fig = px.scatter(
                latent, x="dim1", y="dim2", color=latent[color_by].astype(str),
                hover_data=["accession", "family"], height=600,
                labels={"color": color_by},
                title="Projeção 2D dos embeddings (UMAP/t-SNE)",
            )
            fig.update_traces(marker=dict(size=7, opacity=0.75))
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            st.scatter_chart(latent, x="dim1", y="dim2", color=color_by)

        for name in ("latent_by_family.png", "latent_by_spillover.png"):
            p = FIGURES / name
            if p.exists():
                st.image(str(p), caption=name)

# ----- Ranking -----
with tab_rank:
    ranking = load_ranking()
    if ranking is None:
        st.info("Execute `make evaluate` para gerar o ranking de priorização.")
    else:
        fams = ["(todas)"] + sorted(ranking["family"].dropna().unique().tolist())
        sel = st.selectbox("Filtrar por família", fams)
        view = ranking if sel == "(todas)" else ranking[ranking["family"] == sel]
        top_n = st.slider("Top N", 5, min(200, len(view)), min(25, len(view)))
        st.dataframe(view.head(top_n), use_container_width=True, hide_index=True)
        st.download_button(
            "Baixar ranking (CSV)", view.to_csv(index=False).encode(),
            "virus_priority_ranking.csv", "text/csv",
        )

# ----- Métricas -----
with tab_metrics:
    if metrics is None:
        st.info("Execute `make finetune` para gerar as métricas.")
    else:
        st.subheader("Validação cruzada (estratificada por família)")
        st.json(metrics.get("cv", {}))
        if metrics.get("cross_family"):
            st.subheader("Validação entre famílias (holdout)")
            st.json(metrics["cross_family"])

# ----- Dados -----
with tab_data:
    st.dataframe(
        df.drop(columns=["sequence"], errors="ignore"),
        use_container_width=True, hide_index=True,
    )
