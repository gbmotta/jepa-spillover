"""Geração de embeddings genômicos.

Dois backends:
- ``kmer_pca``: frequências de k-mers reduzidas por PCA (baseline rápido, sem GPU).
- ``transformer``: gancho para codificadores baseados em Transformer de DNA
  (ex.: DNABERT/Nucleotide Transformer via Hugging Face) — opcional.

Gera ``data/processed/embeddings.npz`` com a matriz de embeddings e os accessions.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Config
from ..data.kmers import kmer_matrix


def kmer_pca_embeddings(sequences, *, k: int, dim: int, seed: int) -> np.ndarray:
    """Embeddings por PCA sobre frequências de k-mers."""
    from sklearn.decomposition import PCA

    mat, _ = kmer_matrix(sequences, k=k, normalize=True)
    n_comp = min(dim, mat.shape[0], mat.shape[1])
    pca = PCA(n_components=n_comp, random_state=seed)
    emb = pca.fit_transform(mat)
    if emb.shape[1] < dim:  # pad para a dimensão alvo
        emb = np.pad(emb, ((0, 0), (0, dim - emb.shape[1])))
    return emb.astype(np.float32)


def transformer_embeddings(sequences, *, model_name: str, device: str) -> np.ndarray:
    """Embeddings via codificador Transformer de DNA (Hugging Face).

    Requer `transformers` e `torch`. Mantido simples; ajuste o pooling conforme o modelo.
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModel.from_pretrained(model_name, trust_remote_code=True).to(device).eval()
    out = []
    with torch.no_grad():
        for seq in sequences:
            enc = tok(seq[:4000], return_tensors="pt", truncation=True, max_length=512).to(device)
            hidden = model(**enc).last_hidden_state
            out.append(hidden.mean(dim=1).squeeze(0).cpu().numpy())
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

    if backend == "transformer":
        from ..config import get_device

        device = get_device(cfg.get_path("project.device", "auto"))
        model_name = cfg.get_path("features.embeddings.model_name", "InstaDeepAI/nucleotide-transformer-500m-human-ref")
        print(f"[embeddings] backend=transformer ({model_name}, device={device})")
        emb = transformer_embeddings(sequences, model_name=model_name, device=device)
    else:
        print(f"[embeddings] backend=kmer_pca (k={k}, dim={dim})")
        emb = kmer_pca_embeddings(sequences, k=k, dim=dim, seed=seed)

    out = cfg.resolve("data_processed") / "embeddings.npz"
    np.savez_compressed(out, embeddings=emb, accession=df["accession"].to_numpy())
    print(f"[embeddings] Salvo {out} — shape {emb.shape}")
    return out
