#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
JEPA-Spillover — download VirusHostDB (relações vírus–hospedeiro)
=============================================================================
Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
Módulo  : scripts/download_virushostdb.py

Propósito
---------
Baixa a tabela TSV pública do VirusHostDB (GenomeNet / Kyoto), usada na
curadoria para gerar ``spillover_label`` (host humano vs. não-humano).

Saídas
------
- ``data/external/virushostdb/virushostdb.tsv``
- manifesto JSON com SHA-256 e contagem de linhas

Uso
---
    python scripts/download_virushostdb.py --config config/config.yaml
    python scripts/download_virushostdb.py --debug
=============================================================================
"""

from __future__ import annotations

import argparse

from _utils import PROJECT_ROOT, download_file, write_manifest
from jepa_spillover.config import Config
from jepa_spillover.logger import get_logger

log = get_logger("scripts.download_virushostdb")


def main() -> None:
    """CLI: download VirusHostDB → TSV + manifesto."""
    parser = argparse.ArgumentParser(description="Download do VirusHostDB (TSV)")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        import os
        os.environ["JEPA_LOG_LEVEL"] = "DEBUG"
        from jepa_spillover.logger import set_log_level
        set_log_level("DEBUG")


    cfg = Config.load(args.config)
    url = cfg.get_path(
        "data_sources.virushostdb.url",
        "https://www.genome.jp/ftp/db/virushostdb/virushostdb.tsv",
    )
    out_dir = cfg.resolve("data_external") / "virushostdb"
    target = out_dir / "virushostdb.tsv"

    log.info("VirusHostDB → %s", target)
    download_file(url, target)

    n = sum(1 for _ in open(target, encoding="utf-8")) - 1
    write_manifest(target, source_url=url, n_records=max(n, 0))
    log.info("VirusHostDB: %d relações vírus-hospedeiro salvas", n)


if __name__ == "__main__":
    main()
