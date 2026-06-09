"""Testes leves do pipeline (não exigem dados reais nem GPU)."""

from __future__ import annotations

import numpy as np

from jepa_spillover.data.kmers import kmer_frequencies, kmer_matrix, kmer_vocabulary
from jepa_spillover.data.synthetic import generate
from jepa_spillover.evaluation.metrics import classification_metrics
from jepa_spillover.evaluation.ranking import latent_zoonotic_score


def test_kmer_vocabulary_size():
    assert len(kmer_vocabulary(3)) == 4**3


def test_kmer_frequencies_normalized():
    vocab = kmer_vocabulary(2)
    vec = kmer_frequencies("ACGTACGT", 2, vocab, normalize=True)
    assert abs(vec.sum() - 1.0) < 1e-6


def test_kmer_matrix_shape():
    seqs = ["ACGTACGT", "TTTTGGGG", "ACACACAC"]
    mat, names = kmer_matrix(seqs, k=3)
    assert mat.shape == (3, 4**3)
    assert len(names) == 4**3


def test_synthetic_dataset():
    df = generate(n_per_family=10, seed=0)
    assert len(df) == 50
    assert {"sequence", "family", "spillover_label", "host"}.issubset(df.columns)
    assert set(df["spillover_label"].unique()).issubset({0, 1})


def test_classification_metrics_perfect():
    y = np.array([0, 0, 1, 1])
    score = np.array([0.1, 0.2, 0.8, 0.9])
    m = classification_metrics(y, score)
    assert m["auroc"] == 1.0
    assert 0.0 <= m["brier"] <= 1.0


def test_latent_ranking_runs():
    rng = np.random.default_rng(0)
    emb = rng.normal(size=(40, 16)).astype(np.float32)
    labels = rng.integers(0, 2, size=40)
    scores = latent_zoonotic_score(emb, labels, k=5)
    assert scores.shape == (40,)
    assert (scores >= 0).all() and (scores <= 1).all()
