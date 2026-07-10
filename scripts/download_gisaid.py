#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
JEPA-Spillover — ingestão GISAID (download manual → padronização)
=============================================================================
Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
Módulo  : scripts/download_gisaid.py

Propósito
---------
O GISAID **não** permite download automatizado. Este script apenas processa
FASTA/metadata já baixados manualmente (EpiFlu, EpiCoV, EpiRSV, EpiNiV,
EpiArbo) e os padroniza para o pipeline.

Importante (termos de uso)
--------------------------
Sequências GISAID **não devem ser redistribuídas**. Mantê-las em
``data/raw/gisaid/`` (gitignored) e credenciamento institucional.

Uso
---
    python scripts/download_gisaid.py \
        --epicov downloads/gisaid_hcov.fasta \
        --epiarbo downloads/gisaid_dengue.fasta \
        --config config/config.yaml

Saídas
------
- FASTA padronizados em ``data/raw/gisaid/``
- Manifestos de proveniência
=============================================================================
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from _utils import PROJECT_ROOT, write_manifest
from jepa_spillover.config import Config
from jepa_spillover.logger import get_logger

log = get_logger("scripts.download_gisaid")

# Mapeamento de database GISAID → família viral usada no pipeline
GISAID_DB_TO_FAMILY = {
    "EpiFlu":  "Orthomyxoviridae",
    "EpiCoV":  "Coronaviridae",
    "EpiRSV":  "Paramyxoviridae",    # RSV/Pneumoviridae agrupado com Paramyxo
    "EpiNiV":  "Paramyxoviridae",    # Nipah/Hendra — spillover morcego→humano
    "EpiArbo": "Flaviviridae",       # Dengue, Zika, Chikungunya, Oropouche, WNV
}


def _read_fasta_files(paths: list[Path]) -> list[tuple[str, str]]:
    """Lê múltiplos FASTA e retorna lista de (header, sequência)."""
    records = []
    for path in tqdm(paths, desc="Lendo FASTA", unit="arquivo", ncols=90):
        if not path.exists():
            log.warning("Arquivo não encontrado: %s", path)
            continue
        header, chunks = None, []
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip()
                if line.startswith(">"):
                    if header is not None:
                        records.append((header, "".join(chunks).upper()))
                    header, chunks = line[1:], []
                else:
                    chunks.append(line)
            if header is not None:
                records.append((header, "".join(chunks).upper()))
        log.debug("%s: %d sequências", path.name, len(records))
    return records


def _parse_gisaid_header(header: str, db: str) -> dict:
    """Extrai campos estruturados do cabeçalho FASTA do GISAID."""
    meta: dict = {"gisaid_epi_isl": None, "country": None, "year": None,
                  "subtype": None, "host": None, "db": db}

    # EPI_ISL_XXXXXXX
    if m := re.search(r"EPI_ISL_(\d+)", header):
        meta["gisaid_epi_isl"] = f"EPI_ISL_{m.group(1)}"

    # EpiFlu: A/host/country/id/year|subtype
    if db == "EpiFlu":
        parts = header.split("|")
        if len(parts) >= 2:
            meta["subtype"] = parts[1].strip()
        name_parts = parts[0].split("/")
        if len(name_parts) >= 4:
            meta["host"]    = name_parts[1]
            meta["country"] = name_parts[2]
            try:
                meta["year"] = int(re.search(r"\d{4}", name_parts[3]).group())
            except Exception:
                pass

    # EpiCoV: hCoV-19/country/id/year
    elif db == "EpiCoV":
        parts = header.split("|")
        name_parts = parts[0].split("/")
        if len(name_parts) >= 3:
            meta["country"] = name_parts[1]
            try:
                meta["year"] = int(re.search(r"\d{4}", name_parts[-1]).group())
            except Exception:
                pass
        meta["host"] = "Homo sapiens"

    return meta


def _ingest_db(
    fasta_paths: list[Path],
    db: str,
    out_dir: Path,
    min_length: int,
) -> pd.DataFrame:
    """Lê, filtra e salva sequências de uma base GISAID."""
    records = _read_fasta_files(fasta_paths)
    family = GISAID_DB_TO_FAMILY.get(db, db)
    rows = []
    skipped = 0

    for header, seq in tqdm(records, desc=f"Processando {db}", unit="seq", ncols=90):
        seq = seq.replace("U", "T")
        if len(seq) < min_length:
            skipped += 1
            continue
        meta = _parse_gisaid_header(header, db)
        rows.append({
            "accession":      meta.get("gisaid_epi_isl") or header.split()[0],
            "family":         family,
            "db":             db,
            "subtype":        meta.get("subtype"),
            "host":           meta.get("host"),
            "country":        meta.get("country"),
            "collection_year": meta.get("year"),
            "sequence":       seq,
            "length":         len(seq),
            "source":         "gisaid",
        })

    log.info("[%s] %d sequências aceitas | %d rejeitadas (< %d bp)",
             db, len(rows), skipped, min_length)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Grava FASTA padronizado
    fasta_out = out_dir / f"{db}.fasta"
    with open(fasta_out, "w", encoding="utf-8") as fh:
        for _, row in tqdm(df.iterrows(), total=len(df),
                           desc=f"Gravando {db}.fasta", unit="seq", ncols=90, leave=False):
            fh.write(f">{row['accession']} | {row['family']} | {row['subtype'] or ''}\n")
            fh.write(row["sequence"] + "\n")

    write_manifest(fasta_out, source_url="https://gisaid.org", n_records=len(df), db=db)
    log.info("[%s] salvo: %s (%d seqs)", db, fasta_out, len(df))
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta arquivos GISAID no pipeline")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    parser.add_argument("--epiflu",  nargs="*", default=[], help="FASTA(s) EpiFlu (influenza)")
    parser.add_argument("--epicov",  nargs="*", default=[], help="FASTA(s) EpiCoV (coronavírus)")
    parser.add_argument("--epicsv",  nargs="*", default=[], help="FASTA(s) EpiRSV")
    parser.add_argument("--epiniv",  nargs="*", default=[], help="FASTA(s) EpiNiV (Nipah/Hendra)")
    parser.add_argument("--epiarbo", nargs="*", default=[], help="FASTA(s) EpiArbo (Dengue, Zika, Chik, Oropouche…)")
    parser.add_argument("--metadata", nargs="*", default=[], help="TSV(s) de metadados GISAID")
    parser.add_argument("--min-length", type=int, default=1000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        import os
        os.environ["JEPA_LOG_LEVEL"] = "DEBUG"
        from jepa_spillover.logger import set_log_level
        set_log_level("DEBUG")


    cfg = Config.load(args.config)
    out_dir = cfg.resolve("data_raw") / "gisaid"
    out_dir.mkdir(parents=True, exist_ok=True)

    dfs = []
    db_map = {
        "EpiFlu":  [Path(p) for p in (args.epiflu  or [])],
        "EpiCoV":  [Path(p) for p in (args.epicov  or [])],
        "EpiRSV":  [Path(p) for p in (args.epicsv  or [])],
        "EpiNiV":  [Path(p) for p in (args.epiniv  or [])],
        "EpiArbo": [Path(p) for p in (args.epiarbo or [])],
    }

    for db, paths in db_map.items():
        if not paths:
            log.debug("[%s] nenhum arquivo fornecido — pulando", db)
            continue
        df = _ingest_db(paths, db, out_dir, min_length=args.min_length)
        if not df.empty:
            dfs.append(df)

    if args.metadata:
        log.info("Carregando %d arquivo(s) de metadados...", len(args.metadata))
        meta_dfs = []
        for p in [Path(p) for p in args.metadata]:
            if p.exists():
                meta_dfs.append(pd.read_csv(p, sep="\t", low_memory=False))
                log.debug("Metadados carregados: %s (%d linhas)", p.name, len(meta_dfs[-1]))
        if meta_dfs:
            meta_all = pd.concat(meta_dfs, ignore_index=True)
            # Colunas que podem ter valores mistos (ex.: "S: 721; M: 4385") → string
            for col in meta_all.columns:
                if meta_all[col].dtype == object:
                    meta_all[col] = meta_all[col].astype(str)
            meta_path = out_dir / "metadata.parquet"
            meta_all.to_parquet(meta_path)
            log.info("Metadados salvos: %s (%d linhas, %d colunas)",
                     meta_path, len(meta_all), len(meta_all.columns))

    if dfs:
        combined = pd.concat(dfs, ignore_index=True)
        combined.to_parquet(out_dir / "gisaid_combined.parquet")
        log.info("Total GISAID: %d sequências de %d fontes", len(combined), len(dfs))
    else:
        log.warning("Nenhum arquivo GISAID fornecido. Use --epiflu / --epicov / --epicsv.")
        log.info("Exemplo:\n  python scripts/download_gisaid.py "
                 "--epiflu gisaid_influenza.fasta --epicov gisaid_hcov19.fasta")


if __name__ == "__main__":
    main()
