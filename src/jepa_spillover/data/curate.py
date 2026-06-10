"""Curadoria de sequências virais: QC, limpeza e padronização.

Lê FASTA de `data/raw/` (quando disponível) ou gera dados sintéticos, aplica
controle de qualidade e grava um dataset tabular em `data/processed/dataset.parquet`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from ..config import Config
from ..logger import get_logger

log = get_logger(__name__)
VALID_BASES = set("ACGTU")


def _read_fasta(path: Path):
    """Itera (header, sequência) de um arquivo FASTA sem dependências externas."""
    log.debug("Lendo FASTA: %s", path)
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
        log.debug("Sequência rejeitada por comprimento (%d < %d)", len(seq), min_length)
        return False
    frac = ambiguous_fraction(seq)
    if frac > max_ambiguous:
        log.debug("Sequência rejeitada por ambiguidade (%.3f > %.3f)", frac, max_ambiguous)
        return False
    return True


def load_raw_fastas(cfg: Config) -> pd.DataFrame:
    """Carrega FASTAs do NCBI Virus e do GISAID (quando disponível)."""
    all_dfs: list[pd.DataFrame] = []

    # --- NCBI Virus ---
    ncbi_dir = cfg.resolve("data_raw") / "ncbi_virus"
    fastas = sorted(ncbi_dir.glob("*.fasta"))
    log.info("NCBI FASTA encontrados em %s: %d arquivos", ncbi_dir, len(fastas))
    rows: list[dict] = []
    for fasta in tqdm(fastas, desc="NCBI FASTA", unit="arquivo", ncols=90):
        family = fasta.stem
        n_before = len(rows)
        for header, seq in _read_fasta(fasta):
            acc = header.split()[0]
            host = None
            if m := re.search(r"\[host=([^\]]+)\]", header):
                host = m.group(1)
            rows.append({
                "accession": acc,
                "family": family,
                "sequence": seq.replace("U", "T"),
                "length": len(seq),
                "host": host,
                "description": header,
                "source": "ncbi_virus",
            })
        log.debug("[NCBI/%s] %d sequências carregadas", family, len(rows) - n_before)
    if rows:
        all_dfs.append(pd.DataFrame(rows))

    # --- GISAID (EpiCoV, EpiArbo, EpiNiV, EpiFlu, EpiRSV) ---
    gisaid_dir = cfg.resolve("data_raw") / "gisaid"
    gisaid_fastas = sorted(gisaid_dir.glob("*.fasta")) if gisaid_dir.exists() else []
    if gisaid_fastas:
        log.info("GISAID FASTA encontrados em %s: %d arquivos", gisaid_dir, len(gisaid_fastas))

        # Mapeamento base GISAID → família taxonômica do pipeline
        _DB_FAMILY = {
            "EpiCoV":  "Coronaviridae",
            "EpiFlu":  "Orthomyxoviridae",
            "EpiRSV":  "Paramyxoviridae",
            "EpiNiV":  "Paramyxoviridae",
            "EpiArbo": "Flaviviridae",
        }
        g_rows: list[dict] = []
        for fasta in tqdm(gisaid_fastas, desc="GISAID FASTA", unit="arquivo", ncols=90):
            db = fasta.stem  # ex.: EpiCoV, EpiArbo
            family = _DB_FAMILY.get(db, db)
            n_before = len(g_rows)
            for header, seq in _read_fasta(fasta):
                parts = header.split("|")
                acc = parts[0].strip().split()[0]
                host = None
                if m := re.search(r"Human|Homo sapiens", header, re.I):
                    host = "Homo sapiens"
                elif m := re.search(r"\b(bat|morcego|chiroptera)\b", header, re.I):
                    host = "Chiroptera"
                elif m := re.search(r"\b(camel|dromedary)\b", header, re.I):
                    host = "Camelidae"
                g_rows.append({
                    "accession": acc,
                    "family": family,
                    "sequence": seq.replace("U", "T"),
                    "length": len(seq),
                    "host": host,
                    "description": header,
                    "source": f"gisaid_{db.lower()}",
                })
            log.debug("[GISAID/%s] %d sequências carregadas", db, len(g_rows) - n_before)
        if g_rows:
            all_dfs.append(pd.DataFrame(g_rows))
            log.info("GISAID: %d sequências carregadas de %d bases",
                     len(g_rows), len(gisaid_fastas))
    else:
        log.info("Nenhum FASTA GISAID encontrado em %s — usando apenas NCBI", gisaid_dir)

    if not all_dfs:
        return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)


def _subsample(df: pd.DataFrame, max_per_family: int, seed: int) -> pd.DataFrame:
    """Subsample para no máximo `max_per_family` sequências por família."""
    parts = []
    for fam, grp in df.groupby("family"):
        if len(grp) > max_per_family:
            grp = grp.sample(max_per_family, random_state=seed)
            log.info("[subsample] %s: %d → %d seqs", fam, len(grp) + (len(grp) - len(grp)), max_per_family)
        parts.append(grp)
    return pd.concat(parts, ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)


def curate(config_path: str | None = None) -> Path:
    """Executa a curadoria e grava o dataset processado."""
    cfg = Config.load(config_path)
    min_length = int(cfg.get_path("data_sources.ncbi_virus.min_length", 1000))
    max_ambiguous = float(cfg.get_path("curation.remove_ambiguous_frac", 0.01))
    max_per_family = cfg.get_path("curation.max_seqs_per_family", None)
    seed = int(cfg.get_path("project.seed", 42))
    log.info("Iniciando curadoria (min_length=%d, max_ambiguous=%.3f, max_per_family=%s)",
             min_length, max_ambiguous, max_per_family or "ilimitado")

    df = load_raw_fastas(cfg)
    if df.empty:
        log.warning("Nenhum FASTA em data/raw — gerando dataset sintético de demonstração.")
        from .synthetic import generate
        df = generate(seed=seed)
    else:
        before = len(df)
        log.info("QC: avaliando %d sequências...", before)
        mask = [
            passes_qc(s, min_length=min_length, max_ambiguous=max_ambiguous)
            for s in tqdm(df["sequence"], desc="QC", unit="seq", ncols=90)
        ]
        df = df[mask].drop_duplicates(subset="accession").reset_index(drop=True)
        log.info("QC + dedup: %d → %d sequências (removidas %d)", before, len(df), before - len(df))

        if max_per_family:
            before_sub = len(df)
            df = _subsample(df, int(max_per_family), seed)
            log.info("Subsample (max %d/família): %d → %d seqs",
                     int(max_per_family), before_sub, len(df))

    out = cfg.resolve("data_processed")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "dataset.parquet"
    df.to_parquet(path)
    log.info("Dataset salvo em %s (%d sequências, %d famílias)", path, len(df), df["family"].nunique())
    return path
