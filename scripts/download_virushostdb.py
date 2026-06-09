#!/usr/bin/env python
"""Baixa a tabela de relações vírus-hospedeiro do VirusHostDB.

Uso:
    python scripts/download_virushostdb.py --config config/config.yaml
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _utils import PROJECT_ROOT, download_file, write_manifest

from jepa_spillover.config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="Download do VirusHostDB (TSV)")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    args = parser.parse_args()

    cfg = Config.load(args.config)
    url = cfg.get_path(
        "data_sources.virushostdb.url",
        "https://www.genome.jp/ftp/db/virushostdb/virushostdb.tsv",
    )
    out_dir = cfg.resolve("data_external") / "virushostdb"
    target = out_dir / "virushostdb.tsv"

    print(f"[VirusHostDB] {url}")
    download_file(url, target)

    n = sum(1 for _ in open(target, encoding="utf-8")) - 1
    write_manifest(target, source_url=url, n_records=max(n, 0))
    print(f"  Salvo: {target} ({n} linhas)")


if __name__ == "__main__":
    main()
