"""Métricas de avaliação para predição de risco de spillover."""

from __future__ import annotations

import numpy as np


def classification_metrics(y_true, y_score, *, threshold: float = 0.5) -> dict:
    """Calcula AUROC, AUPRC, F1, precisão, recall, especificidade e Brier."""
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    y_true = np.asarray(y_true).astype(int)
    y_score = np.asarray(y_score, dtype=float)
    y_pred = (y_score >= threshold).astype(int)

    metrics: dict[str, float] = {}
    try:
        metrics["auroc"] = float(roc_auc_score(y_true, y_score))
        metrics["auprc"] = float(average_precision_score(y_true, y_score))
    except ValueError:
        metrics["auroc"] = float("nan")
        metrics["auprc"] = float("nan")

    metrics["f1"] = float(f1_score(y_true, y_pred, zero_division=0))
    metrics["precision"] = float(precision_score(y_true, y_pred, zero_division=0))
    metrics["recall"] = float(recall_score(y_true, y_pred, zero_division=0))

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp = int(cm[0, 0]), int(cm[0, 1])
    metrics["specificity"] = float(tn / (tn + fp)) if (tn + fp) else float("nan")
    metrics["brier"] = float(brier_score_loss(y_true, y_score))
    return metrics
