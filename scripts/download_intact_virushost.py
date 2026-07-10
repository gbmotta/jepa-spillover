#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
JEPA-Spillover — download IntAct (interações vírus–hospedeiro)
=============================================================================
Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
Módulo  : scripts/download_intact_virushost.py

Propósito
---------
Baixa o dump completo do IntAct (EMBL-EBI) e filtra pares vírus–hospedeiro.
IntAct agrega VirHostNet, MINT, DIP, HPIDb e outras fontes MITAB.

Saídas
------
- ``data/external/intact/intact_virus_host.parquet``
- ``data/external/intact/intact_virus_host.mitab``
- ``intact.zip`` / ``intact.txt`` intermediários

Uso
---
    python scripts/download_intact_virushost.py
    python scripts/download_intact_virushost.py --skip-download
    python scripts/download_intact_virushost.py --debug
=============================================================================
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from jepa_spillover.logger import get_logger

log = get_logger("scripts.intact")

INTACT_ZIP_URL = "https://ftp.ebi.ac.uk/pub/databases/intact/current/psimitab/intact.zip"
OUT_DIR        = Path("data/external/intact")

MITAB_COLS = [
    "idA", "idB", "altA", "altB", "aliasA", "aliasB",
    "method", "authors", "pmid", "taxA", "taxB",
    "type", "source", "identifier", "confidence",
]

# Taxons de vírus conhecidos relevantes para spillover
VIRUS_TAXON_PREFIXES = [
    "taxid:11234",  # Measles
    "taxid:11520",  # Influenza
    "taxid:694009", # Betacoronavirus
    "taxid:2697049",# SARS-CoV-2
    "taxid:694002", # SARS-CoV
    "taxid:349342", # MERS-CoV
    "taxid:12234",  # Nipah
    "taxid:12227",  # Hendra
    "taxid:11266",  # Ebola
    "taxid:186539", # Marburg
    "taxid:11234",  # Paramyxoviridae
    "taxid:11118",  # Coronaviridae
    "taxid:11270",  # Filoviridae
    "taxid:11308",  # Orthomyxoviridae
    "taxid:11561",  # Arenaviridae
    "taxid:35301",  # Flaviviridae
    "taxid:11099",  # Togaviridae
]


def download_zip(url: str, dest: Path, chunk_size: int = 1 << 20) -> None:
    """Baixa arquivo grande com barra de progresso."""
    log.info("Baixando %s → %s", url, dest)
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    total = int(r.headers.get("Content-Length", 0))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f, tqdm(
        total=total, unit="B", unit_scale=True, desc="intact.zip", ncols=90
    ) as bar:
        for chunk in r.iter_content(chunk_size):
            f.write(chunk)
            bar.update(len(chunk))
    log.info("Download concluído: %s (%.0f MB)", dest, dest.stat().st_size / 1e6)


def is_virus_taxon(taxon_str: str) -> bool:
    """Retorna True se o taxon pertence a um vírus."""
    if not isinstance(taxon_str, str):
        return False
    # Vírus têm taxids negativos no IntAct (convenção) ou taxids conhecidos
    # Também verificamos se o campo contém "Viridae", "virus" no alias
    taxid = ""
    if "taxid:" in taxon_str:
        taxid = taxon_str.split("taxid:")[1].split("(")[0].split("|")[0].strip()
    # Taxid negativo = vírus sintético/genérico no IntAct
    try:
        if int(taxid) < 0:
            return True
    except (ValueError, TypeError):
        pass
    # Verificar lista de prefixos conhecidos
    for prefix in VIRUS_TAXON_PREFIXES:
        if prefix in taxon_str:
            return True
    # Verificar nome contendo "virus" ou "viridae"
    lower = taxon_str.lower()
    return any(kw in lower for kw in ["virus", "viridae", "phage", "viricota"])


def filter_virus_host(intact_file: Path, out_mitab: Path, out_parquet: Path) -> None:
    """Lê o MITAB em chunks e filtra interações vírus-hospedeiro."""
    log.info("Filtrando interações vírus-hospedeiro de %s ...", intact_file)

    chunks_vh: list[pd.DataFrame] = []
    total_read = 0
    total_vh   = 0
    chunk_size = 100_000

    reader = pd.read_csv(
        intact_file,
        sep="\t",
        header=0,
        names=MITAB_COLS,
        usecols=list(range(15)),
        dtype=str,
        chunksize=chunk_size,
        on_bad_lines="skip",
    )

    with tqdm(desc="Filtrando chunks", unit="linhas", unit_scale=True, ncols=90) as bar:
        for chunk in reader:
            total_read += len(chunk)
            bar.update(len(chunk))

            # Filtrar: pelo menos um parceiro é vírus
            mask = chunk["taxA"].apply(is_virus_taxon) | chunk["taxB"].apply(is_virus_taxon)
            vh = chunk[mask].copy()

            # Excluir vírus-vírus (ambos vírus) — manter só vírus-hospedeiro
            both_virus = vh["taxA"].apply(is_virus_taxon) & vh["taxB"].apply(is_virus_taxon)
            vh = vh[~both_virus]

            total_vh += len(vh)
            if not vh.empty:
                chunks_vh.append(vh)

    log.info("Total lido: %d | Vírus-Hospedeiro: %d (%.1f%%)",
             total_read, total_vh, 100 * total_vh / max(total_read, 1))

    if not chunks_vh:
        log.warning("Nenhuma interação vírus-hospedeiro encontrada — verificar filtros")
        return

    df = pd.concat(chunks_vh, ignore_index=True)

    # Salvar MITAB filtrado
    out_mitab.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_mitab, sep="\t", index=False)
    log.info("MITAB filtrado salvo: %s", out_mitab)

    # Enriquecer e salvar Parquet
    for col in ["taxA", "taxB"]:
        df[col + "_id"]   = df[col].str.extract(r"taxid:(-?\d+)", expand=False)
        df[col + "_name"] = df[col].str.extract(r"\(([^)]+)\)", expand=False)

    df.to_parquet(out_parquet, index=False)
    log.info("Parquet salvo: %s — shape %s", out_parquet, df.shape)

    # Resumo por vírus
    top_viruses = (
        df[df["taxA"].apply(is_virus_taxon)]["taxA_name"]
        .value_counts()
        .head(15)
    )
    log.info("Top 15 vírus com mais interações:\n%s", top_viruses.to_string())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-download", action="store_true",
                        help="Pular download se o zip já existe")
    parser.add_argument("--output", default=str(OUT_DIR))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.debug:
        import os
        os.environ["JEPA_LOG_LEVEL"] = "DEBUG"
        from jepa_spillover.logger import set_log_level
        set_log_level("DEBUG")

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    zip_path = out / "intact.zip"
    tsv_path = out / "intact.txt"

    # Download
    if not args.skip_download or not zip_path.exists():
        download_zip(INTACT_ZIP_URL, zip_path)
    else:
        log.info("Skip download — usando %s existente", zip_path)

    # Extrair
    if not tsv_path.exists():
        log.info("Extraindo %s ...", zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.namelist()
            log.info("Arquivos no zip: %s", members)
            # O arquivo principal é intact.txt ou intact-micluster.txt
            main_file = next((m for m in members if m.endswith(".txt")), members[0])
            log.info("Extraindo %s ...", main_file)
            with zf.open(main_file) as src, open(tsv_path, "wb") as dst:
                total = zf.getinfo(main_file).file_size
                with tqdm(total=total, unit="B", unit_scale=True,
                          desc="Extraindo", ncols=90) as bar:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        dst.write(chunk)
                        bar.update(len(chunk))
        log.info("Extração concluída: %s", tsv_path)
    else:
        log.info("TSV já existe: %s", tsv_path)

    # Filtrar vírus-hospedeiro
    filter_virus_host(
        intact_file=tsv_path,
        out_mitab=out / "intact_virus_host.mitab",
        out_parquet=out / "intact_virus_host.parquet",
    )

    log.info("Concluído! Dados em: %s", out)


if __name__ == "__main__":
    main()
