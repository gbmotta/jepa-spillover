"""Visualização do espaço latente (UMAP/t-SNE) e figuras de avaliação."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Config


def reduce_2d(emb: np.ndarray, *, reducer: str, seed: int, **kwargs) -> np.ndarray:
    """Projeta embeddings em 2D via UMAP (preferencial) ou t-SNE (fallback)."""
    n = len(emb)
    if reducer == "umap":
        try:
            import umap

            nn = min(kwargs.get("n_neighbors", 15), max(2, n - 1))
            return umap.UMAP(
                n_neighbors=nn, min_dist=kwargs.get("min_dist", 0.1),
                random_state=seed,
            ).fit_transform(emb)
        except ImportError:
            pass
    from sklearn.manifold import TSNE

    perplexity = min(30, max(5, n // 4))
    return TSNE(n_components=2, perplexity=perplexity, random_state=seed).fit_transform(emb)


def make_figures(config_path: str | None = None) -> Path:
    cfg = Config.load(config_path)
    seed = int(cfg.get_path("project.seed", 42))
    proc = cfg.resolve("data_processed")

    df = pd.read_parquet(proc / "dataset.parquet")
    emb_path = proc / "jepa_embeddings.npz"
    if not emb_path.exists():
        emb_path = proc / "embeddings.npz"
    data = np.load(emb_path, allow_pickle=True)
    order = {a: i for i, a in enumerate(data["accession"].astype(str))}
    idx = df["accession"].astype(str).map(order).to_numpy()
    emb = data["embeddings"][idx]

    coords = reduce_2d(
        emb,
        reducer=cfg.get_path("viz.reducer", "umap"),
        seed=seed,
        n_neighbors=cfg.get_path("viz.n_neighbors", 15),
        min_dist=cfg.get_path("viz.min_dist", 0.1),
    )
    df = df.copy()
    df["dim1"], df["dim2"] = coords[:, 0], coords[:, 1]

    fig_dir = cfg.resolve("figures")
    fig_dir.mkdir(parents=True, exist_ok=True)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Figura 1: colorido por família
    fig, ax = plt.subplots(figsize=(8, 6))
    for fam, sub in df.groupby("family"):
        ax.scatter(sub["dim1"], sub["dim2"], s=12, alpha=0.7, label=fam)
    ax.set_title("Espaço latente JEPA — por família viral")
    ax.set_xlabel("dim 1"); ax.set_ylabel("dim 2")
    ax.legend(fontsize=8, markerscale=1.5)
    fig.tight_layout()
    p1 = fig_dir / "latent_by_family.png"
    fig.savefig(p1, dpi=150); plt.close(fig)

    # Figura 2: colorido por rótulo de spillover
    fig, ax = plt.subplots(figsize=(8, 6))
    sc = ax.scatter(df["dim1"], df["dim2"], c=df["spillover_label"], cmap="coolwarm", s=12, alpha=0.7)
    ax.set_title("Espaço latente JEPA — risco de spillover (rótulo)")
    ax.set_xlabel("dim 1"); ax.set_ylabel("dim 2")
    fig.colorbar(sc, ax=ax, label="zoonótico (1) / não (0)")
    fig.tight_layout()
    p2 = fig_dir / "latent_by_spillover.png"
    fig.savefig(p2, dpi=150); plt.close(fig)

    df[["accession", "family", "spillover_label", "dim1", "dim2"]].to_parquet(proc / "latent_2d.parquet")
    print(f"[viz] Figuras salvas: {p1.name}, {p2.name}")
    return fig_dir
