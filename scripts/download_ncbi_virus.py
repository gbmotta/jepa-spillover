#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
JEPA-Spillover — download de genomas virais (NCBI Entrez) — Lote 1
=============================================================================
Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
Módulo  : scripts/download_ncbi_virus.py

Propósito
---------
Baixa sequências nucleotídicas (FASTA) do NCBI Nucleotide (nuccore) por
família viral, com filtro de comprimento mínimo. Este é o **lote 1**
(famílias prioritárias do ``config.yaml``: Coronaviridae, Filoviridae, etc.).

Entradas
--------
- ``config/config.yaml`` → ``data_sources.ncbi_virus`` (famílias, min_length, max)
- Credenciais Entrez: e-mail + API key via ``config/secrets.yaml`` ou env
  (``NCBI_EMAIL``, ``NCBI_API_KEY``)

Saídas
------
- ``data/raw/ncbi_virus/<Família>.fasta``
- ``data/raw/ncbi_virus/<Família>.fasta.manifest.json`` (SHA-256, n_records)

Dependências
------------
biopython, tqdm, jepa_spillover.{config,logger}

Uso
---
    python scripts/download_ncbi_virus.py --config config/config.yaml
    python scripts/download_ncbi_virus.py --family Coronaviridae --max 200
    python scripts/download_ncbi_virus.py --debug

Notas
-----
- Respeita rate-limit NCBI (~3 req/s sem key; ~10 req/s com key).
- Não sobrescreve lógica de lote 2 (ver ``download_ncbi_batch2.py``).
=============================================================================
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from _utils import PROJECT_ROOT, write_manifest
from tqdm import tqdm

from jepa_spillover.config import Config
from jepa_spillover.logger import get_logger

log = get_logger("scripts.download_ncbi")


def fetch_family(entrez, family: str, *, min_length: int, max_records: int) -> str:
    """Busca e baixa FASTA de uma família viral via Entrez (nuccore).

    Parameters
    ----------
    entrez :
        Módulo ``Bio.Entrez`` já configurado (email / api_key).
    family :
        Nome da família (ex.: ``"Coronaviridae"``).
    min_length :
        Comprimento mínimo da sequência em bp.
    max_records :
        Máximo de IDs retornados pelo esearch.

    Returns
    -------
    str
        Conteúdo FASTA concatenado (pode ser vazio se nenhum ID).
    """
    query = f'"{family}"[Organism] AND {min_length}:99999999[Sequence Length]'
    log.debug("Entrez esearch: %s", query)

    handle = entrez.esearch(db="nuccore", term=query, retmax=max_records, idtype="acc")
    record = entrez.read(handle)
    handle.close()
    ids = record["IdList"]
    log.info("[%s] %d IDs encontrados", family, len(ids))

    if not ids:
        return ""

    fasta_chunks: list[str] = []
    batch = 200
    batches = range(0, len(ids), batch)

    with tqdm(total=len(ids), desc=family, unit="seq", ncols=90) as bar:
        for start in batches:
            subset = ids[start : start + batch]
            log.debug("[%s] efetch lote %d-%d", family, start, start + len(subset))
            try:
                fetch = entrez.efetch(
                    db="nuccore", id=",".join(subset), rettype="fasta", retmode="text"
                )
                chunk = fetch.read()
                fetch.close()
                fasta_chunks.append(chunk)
                bar.update(len(subset))
                time.sleep(0.34)
            except Exception as exc:
                log.warning("[%s] erro no lote %d: %s — pulando", family, start, exc)
                bar.update(len(subset))

    return "".join(fasta_chunks)


def main() -> None:
    """CLI: baixa famílias do lote 1 conforme ``config.yaml`` / flags."""
    parser = argparse.ArgumentParser(description="Download de genomas virais do NCBI Virus")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    parser.add_argument("--family", action="append", help="Restringe a uma ou mais famílias")
    parser.add_argument("--max", type=int, default=None)
    parser.add_argument("--debug", action="store_true", help="Ativa log DEBUG")
    args = parser.parse_args()

    if args.debug:
        import os
        os.environ["JEPA_LOG_LEVEL"] = "DEBUG"
        from jepa_spillover.logger import set_log_level
        set_log_level("DEBUG")


    cfg = Config.load(args.config)
    src = cfg.get_path("data_sources.ncbi_virus", {})
    email = src.get("email")

    if not email or "exemplo.org" in email:
        raise SystemExit(
            "Defina um e-mail real em config.yaml → data_sources.ncbi_virus.email"
        )

    try:
        from Bio import Entrez
    except ImportError as exc:
        raise SystemExit("Biopython é necessário: pip install biopython") from exc

    Entrez.email = email
    if src.get("api_key"):
        Entrez.api_key = src["api_key"]
        log.info("API key do NCBI configurada via env/secrets (10 req/s)")
    else:
        log.warning(
            "Sem NCBI_API_KEY — limite ~3 req/s. "
            "Defina em config/secrets.yaml ou export NCBI_API_KEY=..."
        )

    families = args.family or src.get("families", [])
    min_length = int(src.get("min_length", 1000))
    max_records = int(args.max or src.get("max_records_per_family", 5000))

    out_dir = cfg.resolve("data_raw") / "ncbi_virus"
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info("Saída: %s | Famílias: %s | min_len=%d | max=%d",
             out_dir, families, min_length, max_records)

    for family in tqdm(families, desc="Famílias", unit="família", ncols=90):
        log.info("=== %s ===", family)
        try:
            fasta = fetch_family(Entrez, family, min_length=min_length, max_records=max_records)
        except Exception as exc:
            log.error("[%s] falha: %s", family, exc)
            continue

        if not fasta.strip():
            log.warning("[%s] nenhuma sequência retornada", family)
            continue

        target = out_dir / f"{family}.fasta"
        target.write_text(fasta, encoding="utf-8")
        n = fasta.count(">")
        write_manifest(target, source_url=f"https://www.ncbi.nlm.nih.gov/nuccore/?term={family}",
                       n_records=n, family=family, min_length=min_length)
        log.info("[%s] salvo: %s (%d sequências)", family, target, n)

    log.info("Download NCBI Virus concluído. FASTA em %s", out_dir)


if __name__ == "__main__":
    main()
