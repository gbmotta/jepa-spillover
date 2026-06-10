"""Gerador de dados sintéticos para testar o pipeline ponta a ponta.


Cria sequências virais artificiais com "assinaturas" de composição por família,
metadados de hospedeiro e rótulos de risco. Útil para demonstração, testes e CI,
enquanto os dados reais não estão baixados.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from tqdm import tqdm

from ..logger import get_logger

log = get_logger(__name__)

FAMILIES = [
    "Coronaviridae",
    "Filoviridae",
    "Paramyxoviridae",
    "Orthomyxoviridae",
    "Arenaviridae",
]

HOSTS = ["Homo sapiens", "Chiroptera", "Aves", "Rodentia", "Suidae", "Primates"]

# Composições de bases muito distintas por família (A, C, G, T)
# + motivos curtos específicos que se repetem, dando sinal real aos k-mers
_FAMILY_PROFILES = {
    "Coronaviridae":    {"weights": np.array([0.32, 0.18, 0.18, 0.32]), "motif": "AATAAA"},
    "Filoviridae":      {"weights": np.array([0.15, 0.35, 0.35, 0.15]), "motif": "GCGCGC"},
    "Paramyxoviridae":  {"weights": np.array([0.28, 0.22, 0.22, 0.28]), "motif": "ATGATG"},
    "Orthomyxoviridae": {"weights": np.array([0.20, 0.30, 0.20, 0.30]), "motif": "CCGGCC"},
    "Arenaviridae":     {"weights": np.array([0.25, 0.25, 0.35, 0.15]), "motif": "GGGAAA"},
}


def _biased_sequence(rng: np.random.Generator, length: int, weights: np.ndarray,
                     motif: str = "") -> str:
    """Gera sequência com composição e motivo específicos da família."""
    bases = np.array(list("ACGT"))
    idx = rng.choice(len(bases), size=length, p=weights / weights.sum())
    seq = list("".join(bases[idx]))
    # Insere o motivo da família a cada ~80 bases para criar sinal k-mer consistente
    if motif:
        step = max(80, length // 15)
        for pos in range(0, length - len(motif), step):
            seq[pos : pos + len(motif)] = list(motif)
    return "".join(seq)


def generate(
    n_per_family: int = 120,
    *,
    min_len: int = 1200,
    max_len: int = 3000,
    seed: int = 42,
) -> pd.DataFrame:
    """Retorna um DataFrame com sequências sintéticas + metadados + rótulos."""
    log.info(
        "Gerando dados sintéticos: %d famílias × %d seqs (seed=%d)",
        len(FAMILIES), n_per_family, seed,
    )
    rng = np.random.default_rng(seed)
    rows = []
    for fi, family in enumerate(tqdm(FAMILIES, desc="Famílias", unit="família", ncols=90)):
        profile = _FAMILY_PROFILES[family]
        noise = rng.dirichlet(np.ones(4) * 20) * 0.04
        base_weights = profile["weights"] + noise
        zoonotic_p = [0.70, 0.60, 0.50, 0.65, 0.45][fi]
        log.debug("[%s] p_zoonótico=%.2f, weights=%s", family, zoonotic_p, base_weights.round(3))
        for j in range(n_per_family):
            length = int(rng.integers(min_len, max_len))
            seq = _biased_sequence(rng, length, base_weights, profile["motif"])
            is_zoo = rng.random() < zoonotic_p
            host = "Homo sapiens" if (is_zoo and rng.random() < 0.6) else rng.choice(HOSTS)
            n_hosts = int(rng.integers(1, 8)) + (2 if is_zoo else 0)
            rows.append(
                {
                    "accession": f"SYN_{family[:4].upper()}_{j:04d}",
                    "family": family,
                    "sequence": seq,
                    "length": length,
                    "host": host,
                    "n_hosts": n_hosts,
                    "human_infection": bool(host == "Homo sapiens" or (is_zoo and rng.random() < 0.5)),
                    "spillover_label": int(is_zoo),
                    "country": rng.choice(["BR", "US", "CN", "CD", "NG", "DE"]),
                    "collection_year": int(rng.integers(1998, 2025)),
                    "source": "synthetic",
                }
            )
    df = pd.DataFrame(rows).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    log.info("Dataset sintético gerado: %d sequências", len(df))
    return df


if __name__ == "__main__":
    import argparse

    from ..config import Config

    parser = argparse.ArgumentParser(description="Gera dataset sintético de demonstração")
    parser.add_argument("--config", default=None)
    parser.add_argument("--n", type=int, default=120, help="Sequências por família")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    out = cfg.resolve("data_processed")
    out.mkdir(parents=True, exist_ok=True)
    df = generate(n_per_family=args.n, seed=cfg.get_path("project.seed", 42))
    path = out / "dataset.parquet"
    df.to_parquet(path)
    print(f"Dataset sintético salvo em {path} ({len(df)} sequências)")
