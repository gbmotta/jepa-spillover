"""Visualização do espaço latente (UMAP/t-SNE) e figuras de avaliação."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score

from ..config import Config
from ..logger import get_logger

log = get_logger(__name__)


def reduce_2d(emb: np.ndarray, *, reducer: str, seed: int, **kwargs) -> np.ndarray:
    """Projeta embeddings em 2D via UMAP ou t-SNE."""
    n = len(emb)
    log.info("Redução 2D: reducer=%s, n=%d", reducer, n)
    if reducer == "umap":
        try:
            import umap
            nn = min(kwargs.get("n_neighbors", 30), max(2, n - 1))
            md = kwargs.get("min_dist", 0.05)
            log.debug("UMAP: n_neighbors=%d, min_dist=%.3f", nn, md)
            coords = umap.UMAP(
                n_neighbors=nn, min_dist=md,
                random_state=seed, verbose=False,
            ).fit_transform(emb)
            log.info("UMAP concluído: shape %s", coords.shape)
            return coords
        except ImportError:
            log.warning("umap-learn não instalado, usando t-SNE como fallback")
            reducer = "tsne"
    import inspect

    from sklearn.manifold import TSNE
    perplexity = min(kwargs.get("perplexity", 40), max(5, n - 1))
    log.debug("t-SNE: perplexity=%d", perplexity)
    # scikit-learn >= 1.5 renomeou 'n_iter' para 'max_iter'.
    iter_kw = "max_iter" if "max_iter" in inspect.signature(TSNE).parameters else "n_iter"
    coords = TSNE(
        n_components=2, perplexity=perplexity,
        random_state=seed, **{iter_kw: 1000},
    ).fit_transform(emb)
    log.info("t-SNE concluído: shape %s", coords.shape)
    return coords


def _silhouette(coords: np.ndarray, labels: np.ndarray) -> float:
    """Silhouette score para medir qualidade da separação de clusters."""
    try:
        unique = np.unique(labels)
        if len(unique) < 2:
            return 0.0
        return float(silhouette_score(coords, labels, sample_size=min(2000, len(labels))))
    except Exception:
        return 0.0


def make_figures(config_path: str | None = None) -> Path:
    cfg = Config.load(config_path)
    seed = int(cfg.get_path("project.seed", 42))
    proc = cfg.resolve("data_processed")

    df = pd.read_parquet(proc / "dataset.parquet")

    # Escolher embeddings com maior overlap com o dataset atual
    candidates = [proc / f for f in ("jepa_embeddings.npz", "embeddings.npz")]
    candidates = [p for p in candidates if p.exists()]
    if not candidates:
        raise FileNotFoundError("Nenhum arquivo de embeddings encontrado.")
    best_path, best_overlap = candidates[0], -1
    for path in candidates:
        d_tmp = np.load(path, allow_pickle=True)
        ov = df["accession"].astype(str).isin(set(d_tmp["accession"].astype(str))).sum()
        if ov > best_overlap:
            best_overlap, best_path = ov, path
    log.info("Carregando embeddings: %s (overlap=%d)", best_path.name, best_overlap)

    data = np.load(best_path, allow_pickle=True)
    order = {a: i for i, a in enumerate(data["accession"].astype(str))}
    idx_series = df["accession"].astype(str).map(order)
    valid = idx_series.notna()
    df = df[valid].reset_index(drop=True)
    idx = idx_series[valid].astype(int).to_numpy()
    emb = data["embeddings"][idx]
    log.info("Embeddings: shape=%s", emb.shape)

    # Subamostrar para visualização mais clara (mantém proporção por família)
    viz_max = int(cfg.get_path("viz.max_points", 3000))
    if len(df) > viz_max:
        rng = np.random.default_rng(seed)
        # Estratificado por família para não perder famílias pequenas
        per_fam = max(1, viz_max // df["family"].nunique())
        sampled_idx = []
        for _, grp in df.groupby("family"):
            n_take = min(len(grp), per_fam)
            sampled_idx.extend(rng.choice(grp.index, n_take, replace=False).tolist())
        sampled_idx = sorted(sampled_idx)
        df_viz = df.loc[sampled_idx].reset_index(drop=True)
        emb_viz = emb[sampled_idx]
        log.info("Subamostrado para visualização: %d → %d pontos", len(df), len(df_viz))
    else:
        df_viz, emb_viz = df, emb

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import json

    fig_dir = cfg.resolve("figures")
    fig_dir.mkdir(parents=True, exist_ok=True)

    nn      = cfg.get_path("viz.n_neighbors", 30)
    md      = cfg.get_path("viz.min_dist", 0.05)
    perp    = cfg.get_path("viz.tsne_perplexity", 40)
    compare = cfg.get_path("viz.compare_reducers", True)
    family_labels = pd.Categorical(df_viz["family"]).codes

    results: dict[str, dict] = {}

    reducers_to_run = ["umap", "tsne"] if compare else [cfg.get_path("viz.reducer", "umap")]
    log.info("Gerando reduções: %s", reducers_to_run)

    for red in reducers_to_run:
        t0 = time.time()
        coords = reduce_2d(
            emb_viz, reducer=red, seed=seed,
            n_neighbors=nn, min_dist=md, perplexity=perp,
        )
        elapsed = time.time() - t0
        sil = _silhouette(coords, family_labels)
        results[red] = {"coords": coords, "silhouette": sil, "time_s": round(elapsed, 1)}
        log.info("%s — silhouette=%.4f, tempo=%.1fs", red.upper(), sil, elapsed)

    # Escolher melhor redução pelo silhouette score
    best_reducer = max(results, key=lambda r: results[r]["silhouette"])
    log.info("Melhor redutor: %s (silhouette=%.4f)", best_reducer.upper(),
             results[best_reducer]["silhouette"])

    best_coords = results[best_reducer]["coords"]
    df_viz = df_viz.copy()
    df_viz["dim1"], df_viz["dim2"] = best_coords[:, 0], best_coords[:, 1]
    df = df_viz

    # Salvar comparação de redutores
    reducer_summary = {
        r: {"silhouette": v["silhouette"], "time_s": v["time_s"]}
        for r, v in results.items()
    }
    reducer_summary["best"] = best_reducer
    (fig_dir / "reducer_comparison.json").write_text(json.dumps(reducer_summary, indent=2))
    log.info("Comparação de redutores: %s", reducer_summary)

    # Figura comparativa se ambos rodaram
    if compare and len(results) == 2:
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        for ax, (red, res) in zip(axes, results.items()):
            c = res["coords"]
            for fam, sub_idx in df_viz.groupby("family").groups.items():
                sub_c = c[df_viz.index.isin(sub_idx) if hasattr(df_viz.index, 'isin') else sub_idx]
                # usar posição relativa ao df_viz
                mask = df_viz["family"] == fam
                ax.scatter(c[mask.values, 0], c[mask.values, 1], s=14, alpha=0.75, label=fam)
            marker = "★ " if red == best_reducer else ""
            ax.set_title(f"{marker}{red.upper()} — silhouette={res['silhouette']:.4f} ({res['time_s']}s)")
            ax.set_xlabel("dim 1"); ax.set_ylabel("dim 2")
            ax.legend(fontsize=7, markerscale=1.5)
        fig.suptitle("Comparação UMAP vs t-SNE — espaço latente viral", fontsize=13, fontweight="bold")
        fig.tight_layout()
        p_cmp = fig_dir / "reducer_comparison.png"
        fig.savefig(p_cmp, dpi=150); plt.close(fig)
        log.info("Figura comparativa salva: %s", p_cmp)

    log.info("Gerando figuras principais em %s...", fig_dir)

    # Figura por família
    fig, ax = plt.subplots(figsize=(9, 7))
    for fam, sub in df.groupby("family"):
        ax.scatter(sub["dim1"], sub["dim2"], s=18, alpha=0.8, label=fam)
    ax.set_title(f"Espaço latente JEPA — por família viral ({best_reducer.upper()})")
    ax.set_xlabel("dim 1"); ax.set_ylabel("dim 2")
    ax.legend(fontsize=8, markerscale=1.5)
    fig.tight_layout()
    p1 = fig_dir / "latent_by_family.png"
    fig.savefig(p1, dpi=150); plt.close(fig)

    # Figura por spillover_label
    has_label = df["spillover_label"].notna()
    fig, ax = plt.subplots(figsize=(9, 7))
    # NaN em cinza claro primeiro
    ax.scatter(df.loc[~has_label, "dim1"], df.loc[~has_label, "dim2"],
               c="#cccccc", s=10, alpha=0.3, label="desconhecido")
    # Negativos (animal) em azul
    neg = has_label & (df["spillover_label"] == 0)
    ax.scatter(df.loc[neg, "dim1"], df.loc[neg, "dim2"],
               c="#3B82F6", s=22, alpha=0.85, label="animal (0)", zorder=3)
    # Positivos (humano) em vermelho
    pos = has_label & (df["spillover_label"] == 1)
    ax.scatter(df.loc[pos, "dim1"], df.loc[pos, "dim2"],
               c="#EF4444", s=22, alpha=0.85, label="humano (1)", zorder=4)
    ax.set_title(f"Espaço latente — spillover label ({best_reducer.upper()})")
    ax.set_xlabel("dim 1"); ax.set_ylabel("dim 2")
    ax.legend(fontsize=9, markerscale=1.5)
    fig.tight_layout()
    p2 = fig_dir / "latent_by_spillover.png"
    fig.savefig(p2, dpi=150); plt.close(fig)

    df[["accession", "family", "spillover_label", "dim1", "dim2"]].to_parquet(proc / "latent_2d.parquet")
    log.info("Figuras salvas: %s, %s | melhor redutor: %s", p1.name, p2.name, best_reducer)
    return fig_dir
