"""Fine-tuning supervisionado para predição de risco de spillover.

Treina uma cabeça de classificação leve sobre os embeddings JEPA (congelados),
com validação cruzada estratificada e validação entre famílias (holdout).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

from ..config import Config, set_global_seed
from ..evaluation.metrics import classification_metrics
from ..logger import get_logger

log = get_logger(__name__)


def _load_embeddings(cfg: Config) -> tuple[np.ndarray, pd.DataFrame]:
    """Carrega embeddings JEPA (preferencial) ou k-mer/PCA, alinhados ao dataset."""
    proc = cfg.resolve("data_processed")
    df = pd.read_parquet(proc / "dataset.parquet")
    for fname in ("jepa_embeddings.npz", "embeddings.npz"):
        path = proc / fname
        if path.exists():
            data = np.load(path, allow_pickle=True)
            order = {a: i for i, a in enumerate(data["accession"].astype(str))}
            idx = df["accession"].astype(str).map(order)
            emb = data["embeddings"][idx.to_numpy()]
            log.info("Usando embeddings de %s — shape %s", fname, emb.shape)
            return emb.astype(np.float32), df
    raise FileNotFoundError("Nenhum arquivo de embeddings encontrado. Rode 'features' ou 'train' antes.")


def finetune(config_path: str | None = None) -> Path:
    cfg = Config.load(config_path)
    seed = int(cfg.get_path("project.seed", 42))
    set_global_seed(seed)

    X, df = _load_embeddings(cfg)
    y = df["spillover_label"].to_numpy()
    families = df["family"].to_numpy()
    log.info("Fine-tune: %d amostras, %d features, seed=%d", len(y), X.shape[1], seed)

    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedGroupKFold

    folds = int(cfg.get_path("finetune.cv_folds", 5))
    skf = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)

    oof = np.zeros(len(y), dtype=np.float32)
    splits = list(skf.split(X, y, groups=families))
    for fold, (tr, te) in enumerate(tqdm(splits, desc="CV folds", unit="fold", ncols=90)):
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)
        clf.fit(X[tr], y[tr])
        oof[te] = clf.predict_proba(X[te])[:, 1]
        log.debug("Fold %d/%d — n_train=%d n_test=%d", fold + 1, folds, len(tr), len(te))

    cv_metrics = classification_metrics(y, oof)
    log.info("CV métricas: AUROC=%.3f AUPRC=%.3f F1=%.3f",
             cv_metrics["auroc"], cv_metrics["auprc"], cv_metrics["f1"])

    holdout = cfg.get_path("finetune.holdout_families", []) or []
    cross_family: dict = {}
    if holdout:
        mask = np.isin(families, holdout)
        if mask.any() and (~mask).any():
            log.info("Holdout inter-família: %s (%d amostras)", holdout, mask.sum())
            clf = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)
            clf.fit(X[~mask], y[~mask])
            proba = clf.predict_proba(X[mask])[:, 1]
            cross_family = classification_metrics(y[mask], proba)
            cross_family["holdout_families"] = list(holdout)
            cross_family["n_holdout"] = int(mask.sum())
            log.info("Cross-family AUROC=%.3f", cross_family["auroc"])

    log.info("Treinando modelo final em todos os dados...")
    final = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)
    final.fit(X, y)
    df = df.copy()
    df["spillover_score"] = final.predict_proba(X)[:, 1]

    out = cfg.resolve("metrics")
    out.mkdir(parents=True, exist_ok=True)
    report = {"cv": cv_metrics, "cross_family": cross_family, "n_samples": int(len(y))}
    (out / "finetune_metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    df.to_parquet(cfg.resolve("data_processed") / "scored.parquet")

    log.info("Métricas (CV): %s", json.dumps(cv_metrics, ensure_ascii=False))
    if cross_family:
        log.info("Validação entre famílias: %s", json.dumps(cross_family, ensure_ascii=False))
    return out / "finetune_metrics.json"
