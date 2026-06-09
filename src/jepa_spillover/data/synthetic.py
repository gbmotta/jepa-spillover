"""Gerador de dados sintéticos para testar o pipeline ponta a ponta.

Cria sequências virais artificiais com "assinaturas" de composição por família,
metadados de hospedeiro e rótulos de risco. Útil para demonstração, testes e CI,
enquanto os dados reais não estão baixados.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FAMILIES = [
    "Coronaviridae",
    "Filoviridae",
    "Paramyxoviridae",
    "Orthomyxoviridae",
    "Arenaviridae",
]

HOSTS = ["Homo sapiens", "Chiroptera", "Aves", "Rodentia", "Suidae", "Primates"]


def _biased_sequence(rng: np.random.Generator, length: int, weights: np.ndarray) -> str:
    """Gera sequência de nucleotídeos com composição enviesada (assinatura da família)."""
    bases = np.array(list("ACGT"))
    idx = rng.choice(len(bases), size=length, p=weights / weights.sum())
    return "".join(bases[idx])


def generate(
    n_per_family: int = 120,
    *,
    min_len: int = 1200,
    max_len: int = 3000,
    seed: int = 42,
) -> pd.DataFrame:
    """Retorna um DataFrame com sequências sintéticas + metadados + rótulos."""
    rng = np.random.default_rng(seed)
    rows = []
    for fi, family in enumerate(FAMILIES):
        # Cada família tem uma composição de bases característica.
        base_weights = rng.dirichlet(np.ones(4) * (2.0 + fi)) + 0.05
        # Probabilidade de zoonose por família (apenas para gerar rótulos plausíveis).
        zoonotic_p = [0.7, 0.6, 0.5, 0.65, 0.45][fi]
        for j in range(n_per_family):
            length = int(rng.integers(min_len, max_len))
            seq = _biased_sequence(rng, length, base_weights)
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
