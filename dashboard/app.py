"""Dashboard interativo do JEPA-Spillover (Streamlit).

Versão autocontida para Hugging Face Spaces — não depende do pacote jepa_spillover.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# No HF Space, app.py fica em /app/app.py; dados em /app/data/
# Localmente, app.py fica em dashboard/; dados na raiz do projeto
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE if (_HERE / "data").exists() else _HERE.parent

PROC     = _ROOT / "data" / "processed"
METRICS  = _ROOT / "results" / "metrics"
RANKINGS = _ROOT / "results" / "rankings"
FIGURES  = _ROOT / "results" / "figures"
KMER_DIR = _ROOT / "results" / "kmer_sweep_full"

st.set_page_config(page_title="JEPA-Spillover", page_icon="🧬", layout="wide")


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

with st.expander("ℹ️ Status do pipeline", expanded=False):
    st.markdown("""
| Etapa | Status | Detalhe |
|---|---|---|
| Coleta de dados | ✅ Concluído | ~51k sequências (NCBI + GISAID) |
| Curadoria | ✅ Concluído | 20k sequências, 10 famílias balanceadas |
| k-mers + PCA | ✅ Concluído | k=4 · AUROC 0.9961 · 8 MB RAM |
| Labels reais (IntAct) | ✅ Concluído | 4.047 humano · 953 animal · 15k NaN |
| Pré-treino JEPA | 🔄 Em execução | RTX 3050 6GB · ~2.5 batch/s |
| Fine-tuning (k-mer PCA) | ✅ Concluído | AUROC 0.449 — aguardando embeddings JEPA |
| Avaliação + ranking | ✅ Concluído | UMAP 20k seqs · ranking gerado |
    """)
    st.caption(
        "⚠️ AUROC atual (0.449) reflete features k-mer PCA — após o pré-treino JEPA "
        "completar, embeddings supervisionados devem elevar AUROC > 0.75."
    )

df = load_dataset()
if df is None:
    st.warning(
        "Nenhum dataset encontrado. Os dados processados ainda não foram publicados neste Space.\n\n"
        "**Repositório do código:** [gbmotta/jepa-spillover](https://huggingface.co/gbmotta/jepa-spillover)"
    )
    st.stop()

# ----- Métricas resumo -----
c1, c2, c3, c4 = st.columns(4)
c1.metric("Vírus", f"{len(df):,}")
c2.metric("Famílias", df["family"].nunique())
if "spillover_label" in df.columns:
    pos = int((df["spillover_label"] == 1).sum())
    neg = int((df["spillover_label"] == 0).sum())
    c3.metric("Labels reais", f"{pos} ✚ / {neg} ✗",
              help="Positivos (humano) / Negativos (animal) — fonte: host NCBI + IntAct")
metrics = load_metrics()
if metrics and metrics.get("cv", {}).get("auroc") is not None:
    c4.metric("AUROC (CV)", f"{metrics['cv']['auroc']:.3f}",
              help="k-mer PCA — melhorará com embeddings JEPA")

tab_latent, tab_rank, tab_metrics, tab_kmer, tab_data = st.tabs(
    ["Espaço latente", "Ranking de priorização", "Métricas", "Benchmark k-mers", "Dados"]
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
        auroc = metrics.get("cv", {}).get("auroc", 0)
        if auroc < 0.6:
            st.warning(
                f"**AUROC atual: {auroc:.3f}** — features k-mer PCA (não-supervisionadas). "
                "Isso é esperado: k-mers distinguem *famílias* virais, não se o vírus "
                "foi isolado de humano ou animal dentro da mesma família. "
                "Após o pré-treino JEPA completar (~esta noite), os embeddings supervisionados "
                "devem elevar o AUROC significativamente."
            )
        st.subheader("Validação cruzada — 5 folds (estratificado por família)")
        cv = metrics.get("cv", {})
        col1, col2, col3 = st.columns(3)
        col1.metric("AUROC", f"{cv.get('auroc', 0):.3f}")
        col2.metric("AUPRC", f"{cv.get('auprc', 0):.3f}")
        col3.metric("F1", f"{cv.get('f1', 0):.3f}")
        st.json(cv)
        if metrics.get("cross_family"):
            st.subheader("Validação entre famílias (holdout: Arenaviridae)")
            cf = metrics["cross_family"]
            col1, col2 = st.columns(2)
            col1.metric("AUROC cross-família", f"{cf.get('auroc', 0):.3f}")
            col2.metric("N holdout", cf.get("n_holdout", "—"))
            st.json(cf)

# ----- Benchmark k-mers -----
with tab_kmer:
    st.subheader("Benchmark k-mers — escolha do k ótimo")
    kmer_results_path = KMER_DIR / "kmer_sweep_results.json"
    kmer_fig_path     = KMER_DIR / "kmer_sweep.png"

    if kmer_results_path.exists():
        kmer_df = pd.DataFrame(json.loads(kmer_results_path.read_text()))
        kmer_df["vocab_size"] = kmer_df["vocab_size"].apply(lambda x: f"{x:,}")
        kmer_df["var_%"] = (kmer_df["var_explained"] * 100).round(1).astype(str) + "%"
        kmer_df["auroc"] = kmer_df["auroc"].round(4)
        kmer_df["peak_ram_mb"] = kmer_df["peak_ram_mb"].round(0).astype(str) + " MB"
        kmer_df["time_s"] = kmer_df["time_s"].round(1).astype(str) + "s"
        st.dataframe(
            kmer_df[["k", "vocab_size", "var_%", "auroc", "time_s", "peak_ram_mb"]],
            use_container_width=True, hide_index=True,
        )
        st.caption("k=4 selecionado como padrão — melhor trade-off AUROC × RAM × tempo.")
    else:
        st.info("Execute `python scripts/kmer_sweep.py` para gerar o benchmark.")

    if kmer_fig_path.exists():
        st.image(str(kmer_fig_path), caption="Benchmark k-mers (AUROC, variância, tempo, RAM)")

# ----- Dados -----
with tab_data:
    st.dataframe(
        df.drop(columns=["sequence"], errors="ignore"),
        use_container_width=True, hide_index=True,
    )
