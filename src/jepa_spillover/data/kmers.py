"""Representação por frequência de k-mers (baseline interpretável).

Modo memory-safe: usa gerador para nunca manter a matriz completa em RAM.
Use `kmer_matrix_chunks` para datasets grandes.
"""

from __future__ import annotations

from itertools import product
from typing import Generator, Iterable

import numpy as np
from tqdm import tqdm

from ..logger import get_logger

log = get_logger(__name__)
ALPHABET = "ACGT"


def kmer_vocabulary(k: int) -> dict[str, int]:
    """Mapeia cada k-mer canônico do alfabeto ACGT para um índice."""
    vocab = {"".join(p): i for i, p in enumerate(product(ALPHABET, repeat=k))}
    log.debug("Vocabulário %d-mers: %d entradas", k, len(vocab))
    return vocab


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


def kmer_matrix_chunks(
    sequences: Iterable[str],
    k: int = 6,
    *,
    normalize: bool = True,
    chunk_size: int = 1000,
    show_progress: bool = True,
) -> Generator[np.ndarray, None, None]:
    """Gera a matriz de k-mers em blocos de `chunk_size` linhas.

    Uso com IncrementalPCA:
        for chunk in kmer_matrix_chunks(seqs, k=6, chunk_size=500):
            ipca.partial_fit(chunk)
    """
    vocab = kmer_vocabulary(k)
    seqs = list(sequences)
    n = len(seqs)
    log.info("k-mers chunk-mode (k=%d, n=%d, chunk=%d)", k, n, chunk_size)
    with tqdm(total=n, desc=f"{k}-mers", unit="seq", ncols=90, disable=not show_progress) as bar:
        for start in range(0, n, chunk_size):
            batch = seqs[start : start + chunk_size]
            chunk = np.vstack([kmer_frequencies(s, k, vocab, normalize=normalize) for s in batch])
            bar.update(len(batch))
            yield chunk


def kmer_matrix(
    sequences,
    k: int = 6,
    *,
    normalize: bool = True,
    show_progress: bool = True,
    chunk_size: int = 2000,
) -> tuple[np.ndarray, list[str]]:
    """Matriz (n_seqs × 4^k) de frequências de k-mers.

    Constrói em chunks para limitar o pico de RAM.
    Para datasets muito grandes use `kmer_matrix_chunks` + IncrementalPCA diretamente.
    """
    vocab = kmer_vocabulary(k)
    seqs = list(sequences)
    log.info("Calculando k-mers (k=%d) para %d sequências...", k, len(seqs))
    chunks = []
    with tqdm(total=len(seqs), desc=f"{k}-mers", unit="seq", ncols=90, disable=not show_progress) as bar:
        for start in range(0, len(seqs), chunk_size):
            batch = seqs[start : start + chunk_size]
            chunks.append(
                np.vstack([kmer_frequencies(s, k, vocab, normalize=normalize) for s in batch])
            )
            bar.update(len(batch))
            del batch  # libera RAM imediatamente
    mat = np.vstack(chunks)
    del chunks
    log.info("Matriz k-mers: %s (%.0f MB)", mat.shape, mat.nbytes / 1e6)
    return mat, list(vocab.keys())
