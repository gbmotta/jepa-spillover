#!/usr/bin/env python
"""Segundo lote de genomas virais do NCBI — famílias adicionais de relevância zoonótica.

Famílias incluídas (complementam o lote 1):
  - Flaviviridae    : Dengue, Zika, Febre Amarela, West Nile, TBEV
  - Phenuiviridae   : Hantavirus, Rift Valley Fever (RVFV)
  - Nairoviridae    : Febre Hemorrágica da Crimeia-Congo (CCHFV)
  - Rhabdoviridae   : Lyssavirus (raiva) + outros
  - Togaviridae     : Chikungunya, Alphavirus
  - Peribunyaviridae: Vírus La Crosse, Oropouche, Bunyamwera
  - Reoviridae      : Rotavirus, Orbivirus (Língua Azul)
  - Picornaviridae  : Vírus de aftosa, enterovirus zoonóticos

Uso:
    python scripts/download_ncbi_batch2.py --config config/config.yaml
    python scripts/download_ncbi_batch2.py --config config/config.yaml --max 2000
    JEPA_LOG_LEVEL=DEBUG python scripts/download_ncbi_batch2.py ...
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from _utils import PROJECT_ROOT, write_manifest
from tqdm import tqdm

from jepa_spillover.config import Config
from jepa_spillover.logger import get_logger

log = get_logger("scripts.download_ncbi_batch2")

# Famílias do 2.º lote com justificativa de relevância zoonótica
BATCH2_FAMILIES = {
    "Flaviviridae":     "Dengue, Zika, Febre Amarela, West Nile, TBEV — alta diversidade zoonótica",
    "Phenuiviridae":    "Hantavirus (Seoul, Sin Nombre), RVFV — roedores/mosquitos → humanos",
    "Nairoviridae":     "CCHFV (Febre Hemorrágica Crimeia-Congo) — carrapatos → humanos/animais",
    "Rhabdoviridae":    "Lyssavirus (raiva), vírus de vesiculite — carnívoros → humanos",
    "Togaviridae":      "Chikungunya, EEEV, WEEV — mosquitos/pássaros → humanos",
    "Peribunyaviridae": "Oropouche, La Crosse, Bunyamwera — insetos → humanos (Brasil relevante)",
    "Reoviridae":       "Rotavirus, Orbivirus, Colorado Tick Fever — gado/carrapatos",
    "Picornaviridae":   "Vírus aftosa, Hepatovirus, Enterovirus zoonóticos",
}


def fetch_family(entrez, family: str, *, min_length: int, max_records: int,
                 max_retries: int = 5) -> str:
    query = f'"{family}"[Organism] AND {min_length}:99999999[Sequence Length]'
    log.debug("Entrez esearch: %s", query)

    # esearch com retry
    for attempt in range(1, max_retries + 1):
        try:
            handle = entrez.esearch(db="nuccore", term=query, retmax=max_records, idtype="acc")
            record = entrez.read(handle)
            handle.close()
            break
        except Exception as exc:
            wait = 2 ** attempt
            log.warning("[%s] esearch falhou (tentativa %d/%d): %s — aguardando %ds",
                        family, attempt, max_retries, exc, wait)
            if attempt == max_retries:
                raise
            time.sleep(wait)

    ids = record["IdList"]
    log.info("[%s] %d IDs encontrados", family, len(ids))
    if not ids:
        return ""

    fasta_chunks: list[str] = []
    batch = 200
    with tqdm(total=len(ids), desc=family, unit="seq", ncols=90) as bar:
        for start in range(0, len(ids), batch):
            subset = ids[start : start + batch]
            for attempt in range(1, max_retries + 1):
                try:
                    fetch = entrez.efetch(
                        db="nuccore", id=",".join(subset), rettype="fasta", retmode="text"
                    )
                    chunk = fetch.read()
                    fetch.close()
                    fasta_chunks.append(chunk)
                    bar.update(len(subset))
                    time.sleep(0.5)   # mais conservador para evitar throttling
                    break
                except Exception as exc:
                    wait = 2 ** attempt
                    log.warning("[%s] lote %d falhou (tentativa %d/%d): %s — aguardando %ds",
                                family, start, attempt, max_retries, exc, wait)
                    if attempt == max_retries:
                        log.error("[%s] lote %d descartado após %d tentativas", family, start, max_retries)
                        bar.update(len(subset))
                    else:
                        time.sleep(wait)

    return "".join(fasta_chunks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lote 2 de genomas virais NCBI — famílias adicionais"
    )
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    parser.add_argument("--family", action="append", help="Restringe a famílias específicas")
    parser.add_argument("--max", type=int, default=3000,
                        help="Máximo de sequências por família (default: 3000)")
    parser.add_argument("--min-length", type=int, default=1000,
                        help="Comprimento mínimo (bp)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        import os
        os.environ["JEPA_LOG_LEVEL"] = "DEBUG"

    cfg = Config.load(args.config)
    email = cfg.get_path("data_sources.ncbi_virus.email")
    if not email or "exemplo.org" in email:
        raise SystemExit("Defina email em config.yaml → data_sources.ncbi_virus.email")

    try:
        from Bio import Entrez
    except ImportError as exc:
        raise SystemExit("pip install biopython") from exc

    Entrez.email = email
    api_key = cfg.get_path("data_sources.ncbi_virus.api_key")
    if api_key:
        Entrez.api_key = api_key
        log.info("API key configurada (10 req/s)")

    families = args.family or list(BATCH2_FAMILIES.keys())
    out_dir = cfg.resolve("data_raw") / "ncbi_virus"
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== NCBI Lote 2: %d famílias | max=%d | min_len=%d ===",
             len(families), args.max, args.min_length)
    for f, desc in BATCH2_FAMILIES.items():
        if f in families:
            log.info("  %-20s %s", f, desc)

    for family in tqdm(families, desc="Lote 2", unit="família", ncols=90):
        target = out_dir / f"{family}.fasta"
        if target.exists():
            n_existing = target.read_text(encoding="utf-8").count(">")
            log.info("[%s] já existe (%d seqs) — pulando (use --force para sobrescrever)",
                     family, n_existing)
            continue

        log.info("=== %s ===", family)
        try:
            fasta = fetch_family(Entrez, family,
                                 min_length=args.min_length, max_records=args.max)
        except Exception as exc:
            log.error("[%s] falha: %s", family, exc)
            continue

        if not fasta.strip():
            log.warning("[%s] nenhuma sequência retornada", family)
            continue

        target.write_text(fasta, encoding="utf-8")
        n = fasta.count(">")
        write_manifest(
            target,
            source_url=f"https://www.ncbi.nlm.nih.gov/nuccore/?term={family}",
            n_records=n,
            family=family,
            batch="lote2",
            min_length=args.min_length,
        )
        log.info("[%s] salvo: %d sequências", family, n)

    log.info("Lote 2 concluído. FASTA em %s", out_dir)


if __name__ == "__main__":
    main()
