"""Curadoria de sequências virais: QC, limpeza e padronização.

Lê FASTA de `data/raw/` (quando disponível) ou gera dados sintéticos, aplica
controle de qualidade e grava um dataset tabular em `data/processed/dataset.parquet`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..config import Config

VALID_BASES = set("ACGTU")


def _read_fasta(path: Path):
    """Itera (header, sequência) de um arquivo FASTA sem dependências externas."""
    header, chunks = None, []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip()
            if line.startswith(">"):
                if header is not None:
                    yield header, "".join(chunks)
                header, chunks = line[1:], []
            else:
                chunks.append(line.upper())
    if header is not None:
        yield header, "".join(chunks)


def ambiguous_fraction(seq: str) -> float:
    if not seq:
        return 1.0
    bad = sum(1 for c in seq if c not in VALID_BASES)
    return bad / len(seq)


def passes_qc(seq: str, *, min_length: int, max_ambiguous: float) -> bool:
    if len(seq) < min_length:
        return False
    if ambiguous_fraction(seq) > max_ambiguous:
        return False
    return True


def load_raw_fastas(cfg: Config) -> pd.DataFrame:
    """Carrega todos os FASTA baixados em `data/raw/ncbi_virus/`."""
    raw_dir = cfg.resolve("data_raw") / "ncbi_virus"
    rows = []
    for fasta in sorted(raw_dir.glob("*.fasta")):
        family = fasta.stem
        for header, seq in _read_fasta(fasta):
            acc = header.split()[0]
            host = None
            if m := re.search(r"\[host=([^\]]+)\]", header):
                host = m.group(1)
            rows.append(
                {
                    "accession": acc,
                    "family": family,
                    "sequence": seq.replace("U", "T"),
                    "length": len(seq),
                    "host": host,
                    "description": header,
                    "source": "ncbi_virus",
                }
            )
    return pd.DataFrame(rows)


def curate(config_path: str | None = None) -> Path:
    """Executa a curadoria e grava o dataset processado."""
    cfg = Config.load(config_path)
    min_length = int(cfg.get_path("data_sources.ncbi_virus.min_length", 1000))
    max_ambiguous = float(cfg.get_path("curation.remove_ambiguous_frac", 0.01))

    df = load_raw_fastas(cfg)
    if df.empty:
        print("[curate] Nenhum FASTA em data/raw — gerando dataset sintético de demonstração.")
        from .synthetic import generate

        df = generate(seed=cfg.get_path("project.seed", 42))
    else:
        before = len(df)
        df = df[df["sequence"].map(lambda s: passes_qc(s, min_length=min_length, max_ambiguous=max_ambiguous))]
        df = df.drop_duplicates(subset="sequence").reset_index(drop=True)
        print(f"[curate] QC + dedup: {before} → {len(df)} sequências")

    out = cfg.resolve("data_processed")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "dataset.parquet"
    df.to_parquet(path)
    print(f"[curate] Dataset salvo em {path} ({len(df)} sequências, {df['family'].nunique()} famílias)")
    return path
