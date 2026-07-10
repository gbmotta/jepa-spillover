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
from ..security import load_npz

log = get_logger(__name__)


def _load_embeddings(cfg: Config) -> tuple[np.ndarray, pd.DataFrame]:
    """Carrega embeddings JEPA (preferencial) ou k-mer/PCA, alinhados ao dataset.

    Filtra sequências sem embedding e sem spillover_label válido.
    """
    proc = cfg.resolve("data_processed")
    df = pd.read_parquet(proc / "dataset.parquet")

    # Candidatos em ordem de preferência; escolhe o com maior overlap com dataset
    candidates = [proc / f for f in ("jepa_embeddings.npz", "embeddings.npz")]
    candidates = [p for p in candidates if p.exists()]
    if not candidates:
        raise FileNotFoundError("Nenhum arquivo de embeddings encontrado. Rode 'features' ou 'train' antes.")

    best_path, best_overlap = candidates[0], -1
    for path in candidates:
        data_tmp = load_npz(path)
        acc_set = set(data_tmp["accession"].astype(str))
        overlap = df["accession"].astype(str).isin(acc_set).sum()
        log.info("Embeddings %s: %d accessions, overlap=%d", path.name, len(acc_set), overlap)
        if overlap > best_overlap:
            best_overlap, best_path = overlap, path

    log.info("Usando %s (maior overlap: %d)", best_path.name, best_overlap)
    data = load_npz(best_path)
    order = {a: i for i, a in enumerate(data["accession"].astype(str))}
    idx = df["accession"].astype(str).map(order)

    # Manter apenas sequências com embedding encontrado
    valid_emb = idx.notna()
    if not valid_emb.all():
        log.warning("embeddings: %d / %d accessions encontrados", valid_emb.sum(), len(df))
        df = df[valid_emb].reset_index(drop=True)
        idx = idx[valid_emb].reset_index(drop=True)

    # Filtrar também por spillover_label não-nulo
    if "spillover_label" in df.columns:
        valid_label = df["spillover_label"].notna()
        if not valid_label.all():
            log.info("Fine-tune: usando %d / %d com spillover_label conhecido",
                     valid_label.sum(), len(df))
            df = df[valid_label].reset_index(drop=True)
            idx = idx[valid_label].reset_index(drop=True)

    emb = data["embeddings"][idx.astype(int).to_numpy()]
    log.info("Embeddings carregados — shape %s, %d amostras com label", emb.shape, len(df))
    return emb.astype(np.float32), df


def finetune(config_path: str | None = None) -> Path:
    cfg = Config.load(config_path)
    seed = int(cfg.get_path("project.seed", 42))
    set_global_seed(seed)

    X, df = _load_embeddings(cfg)
    # Garantir inteiros — spillover_label pode ser Int64 nullable
    y = df["spillover_label"].dropna().astype(int).to_numpy()
    # Alinhar X e families ao y filtrado
    valid = df["spillover_label"].notna().to_numpy()
    X = X[valid]
    families = df["family"].to_numpy()[valid]
    log.info("Fine-tune: %d amostras com label, %d features, seed=%d", len(y), X.shape[1], seed)

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
