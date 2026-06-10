"""Ranking de priorização de vírus por proximidade latente a zoonóticos conhecidos.

Para cada vírus, calcula um score de risco combinando:
- densidade de vizinhos zoonóticos no espaço latente (kNN), e
- (quando disponível) o score do classificador supervisionado.
Vírus pouco caracterizados próximos a zoonóticos conhecidos sobem no ranking.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

from ..config import Config
from ..logger import get_logger

log = get_logger(__name__)


def latent_zoonotic_score(emb: np.ndarray, labels: np.ndarray, *, k: int = 25) -> np.ndarray:
    """Fração ponderada de vizinhos zoonóticos no espaço latente (kNN por cosseno)."""
    from sklearn.neighbors import NearestNeighbors

    log.info("Calculando latent_zoonotic_score (k=%d, n=%d)...", k, len(emb))
    norm = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-8)
    k_eff = min(k + 1, len(emb))
    nn = NearestNeighbors(n_neighbors=k_eff, metric="cosine").fit(norm)
    dist, idx = nn.kneighbors(norm)
    scores = np.zeros(len(emb), dtype=np.float32)
    for i in tqdm(range(len(emb)), desc="kNN score", unit="vírus", ncols=90):
        neigh = idx[i][1:]
        w = 1.0 - dist[i][1:]
        zoo = labels[neigh] == 1
        scores[i] = float((w * zoo).sum() / (w.sum() + 1e-8))
    log.debug("latent_zoonotic_score: min=%.3f max=%.3f mean=%.3f",
              scores.min(), scores.max(), scores.mean())
    return scores


def build_ranking(config_path: str | None = None) -> Path:
    cfg = Config.load(config_path)
    proc = cfg.resolve("data_processed")
    log.info("Construindo ranking de priorização...")

    df = pd.read_parquet(proc / "dataset.parquet")
    emb_path = proc / "jepa_embeddings.npz"
    if not emb_path.exists():
        emb_path = proc / "embeddings.npz"
    log.info("Usando embeddings: %s", emb_path.name)
    data = np.load(emb_path, allow_pickle=True)
    order = {a: i for i, a in enumerate(data["accession"].astype(str))}
    idx = df["accession"].astype(str).map(order).to_numpy()
    emb = data["embeddings"][idx]

    labels = df["spillover_label"].to_numpy()
    k = int(cfg.get_path("viz.knn_for_ranking", 25))
    df = df.copy()
    df["latent_zoonotic_score"] = latent_zoonotic_score(emb, labels, k=k)

    scored_path = proc / "scored.parquet"
    if scored_path.exists():
        scored = pd.read_parquet(scored_path)[["accession", "spillover_score"]]
        df = df.merge(scored, on="accession", how="left")
        df["priority_score"] = 0.5 * df["latent_zoonotic_score"] + 0.5 * df["spillover_score"].fillna(0)
        log.info("Score combinado: latent + spillover_score (peso 50/50)")
    else:
        df["priority_score"] = df["latent_zoonotic_score"]
        log.info("Score baseado apenas em latent_zoonotic_score (sem scored.parquet)")

    ranking = df.sort_values("priority_score", ascending=False)
    cols = [c for c in ["accession", "family", "host", "spillover_label",
                        "latent_zoonotic_score", "spillover_score", "priority_score"] if c in ranking.columns]
    ranking = ranking[cols]

    out_dir = cfg.resolve("rankings")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "virus_priority_ranking.csv"
    ranking.to_csv(out, index=False)
    log.info("Ranking salvo: %s (%d vírus)", out, len(ranking))
    log.info("Top 10:\n%s", ranking.head(10).to_string(index=False))
    return out
