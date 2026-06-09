"""Representação por frequência de k-mers (baseline interpretável)."""

from __future__ import annotations

from itertools import product

import numpy as np

ALPHABET = "ACGT"


def kmer_vocabulary(k: int) -> dict[str, int]:
    """Mapeia cada k-mer canônico do alfabeto ACGT para um índice."""
    return {"".join(p): i for i, p in enumerate(product(ALPHABET, repeat=k))}


def kmer_frequencies(seq: str, k: int, vocab: dict[str, int], *, normalize: bool = True) -> np.ndarray:
    """Vetor de frequências de k-mers de uma sequência."""
    vec = np.zeros(len(vocab), dtype=np.float32)
    seq = seq.upper().replace("U", "T")
    for i in range(len(seq) - k + 1):
        idx = vocab.get(seq[i : i + k])
        if idx is not None:
            vec[idx] += 1.0
    if normalize and vec.sum() > 0:
        vec /= vec.sum()
    return vec


def kmer_matrix(sequences, k: int = 6, *, normalize: bool = True) -> tuple[np.ndarray, list[str]]:
    """Matriz (n_seqs × 4^k) de frequências de k-mers."""
    vocab = kmer_vocabulary(k)
    mat = np.vstack([kmer_frequencies(s, k, vocab, normalize=normalize) for s in sequences])
    return mat, list(vocab.keys())
