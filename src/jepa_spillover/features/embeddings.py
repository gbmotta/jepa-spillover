"""Geração de embeddings genômicos.

Dois backends:
- ``kmer_pca``: frequências de k-mers reduzidas por PCA (baseline rápido, sem GPU).
- ``transformer``: gancho para codificadores baseados em Transformer de DNA
  (ex.: DNABERT/Nucleotide Transformer via Hugging Face) — opcional.

Gera ``data/processed/embeddings.npz`` com a matriz de embeddings e os accessions.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

from ..config import Config
from ..data.kmers import kmer_matrix, kmer_matrix_chunks
from ..logger import get_logger

log = get_logger(__name__)


def kmer_pca_embeddings(
    sequences,
    *,
    k: int,
    dim: int,
    seed: int,
    chunk_size: int = 500,
) -> np.ndarray:
    """Embeddings por IncrementalPCA sobre frequências de k-mers.

    Usa IncrementalPCA para nunca manter a matriz completa em RAM:
    processa `chunk_size` sequências por vez na fase de fit e transform.
    """
    from sklearn.decomposition import IncrementalPCA

    seqs = list(sequences)
    n = len(seqs)
    vocab_size = 4 ** k
    n_comp = min(dim, n - 1, vocab_size)
    # IncrementalPCA exige chunk >= n_components
    safe_chunk = max(chunk_size, n_comp + 1)
    log.info("k-mer IncrementalPCA: k=%d, dim=%d, n=%d, chunk=%d", k, n_comp, n, safe_chunk)

    ipca = IncrementalPCA(n_components=n_comp)

    # Fase 1: fit parcial chunk a chunk
    log.info("Fase 1/2: fit IncrementalPCA...")
    for chunk in kmer_matrix_chunks(seqs, k=k, chunk_size=safe_chunk, show_progress=True):
        ipca.partial_fit(chunk)
    var = ipca.explained_variance_ratio_.sum()
    log.info("PCA variância explicada: %.1f%%", var * 100)

    # Fase 2: transform chunk a chunk (nunca aloca a matriz completa)
    log.info("Fase 2/2: transform...")
    parts: list[np.ndarray] = []
    for chunk in kmer_matrix_chunks(seqs, k=k, chunk_size=safe_chunk, show_progress=False):
        parts.append(ipca.transform(chunk).astype(np.float32))
    emb = np.vstack(parts)
    del parts

    if emb.shape[1] < dim:
        emb = np.pad(emb, ((0, 0), (0, dim - emb.shape[1])))
    log.info("Embeddings k-mer PCA: shape=%s (%.0f MB)", emb.shape, emb.nbytes / 1e6)
    return emb


def transformer_embeddings(sequences, *, model_name: str, device: str) -> np.ndarray:
    """Embeddings via codificador Transformer de DNA (Hugging Face).

    Requer `transformers` e `torch`. Mantido simples; ajuste o pooling conforme o modelo.
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    log.info("Carregando modelo Transformer: %s (device=%s)", model_name, device)
    # trust_remote_code só para modelos pinados/confiáveis (ex.: InstaDeepAI).
    allow_remote = os.environ.get("JEPA_TRUST_REMOTE_CODE", "0") == "1"
    if allow_remote:
        log.warning("JEPA_TRUST_REMOTE_CODE=1 — executando código remoto do Hub")
    tok = AutoTokenizer.from_pretrained(model_name, trust_remote_code=allow_remote)
    model = AutoModel.from_pretrained(model_name, trust_remote_code=allow_remote).to(device).eval()
    out = []
    with torch.no_grad():
        for seq in tqdm(sequences, desc="Transformer emb", unit="seq", ncols=90):
            enc = tok(seq[:4000], return_tensors="pt", truncation=True, max_length=512).to(device)
            hidden = model(**enc).last_hidden_state
            out.append(hidden.mean(dim=1).squeeze(0).cpu().numpy())
    log.info("Transformer embeddings: %d sequências processadas", len(out))
    return np.vstack(out).astype(np.float32)


def build_embeddings(config_path: str | None = None) -> Path:
    """Gera embeddings conforme o backend configurado."""
    cfg = Config.load(config_path)
    seed = int(cfg.get_path("project.seed", 42))
    backend = cfg.get_path("features.embeddings.backend", "kmer_pca")
    dim = int(cfg.get_path("features.embeddings.dim", 256))
    k = int(cfg.get_path("features.kmer.k", 6))

    df = pd.read_parquet(cfg.resolve("data_processed") / "dataset.parquet")
    sequences = df["sequence"].tolist()
    log.info("Build embeddings: backend=%s, n=%d seqs", backend, len(sequences))

    chunk_size = int(cfg.get_path("features.kmer.chunk_size", 500))
    pca_chunk  = int(cfg.get_path("features.embeddings.pca_chunk", 500))

    if backend == "transformer":
        from ..config import get_device
        device = get_device(cfg.get_path("project.device", "auto"))
        model_name = cfg.get_path(
            "features.embeddings.model_name",
            "InstaDeepAI/nucleotide-transformer-500m-human-ref",
        )
        emb = transformer_embeddings(sequences, model_name=model_name, device=device)
    else:
        emb = kmer_pca_embeddings(sequences, k=k, dim=dim, seed=seed, chunk_size=pca_chunk)

    out = cfg.resolve("data_processed") / "embeddings.npz"
    np.savez_compressed(out, embeddings=emb, accession=df["accession"].astype(str).to_numpy())
    log.info("Embeddings salvos: %s — shape %s", out, emb.shape)
    return out
