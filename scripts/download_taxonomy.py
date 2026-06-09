#!/usr/bin/env python
"""Baixa e extrai o taxdump do NCBI Taxonomy (padronização taxonômica).

Uso:
    python scripts/download_taxonomy.py --config config/config.yaml
"""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

from _utils import PROJECT_ROOT, download_file, write_manifest

from jepa_spillover.config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="Download do NCBI Taxonomy (taxdump)")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    parser.add_argument("--extract", action="store_true", help="Extrai nodes.dmp/names.dmp")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    url = cfg.get_path(
        "data_sources.taxonomy.ncbi_taxdump",
        "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz",
    )
    out_dir = cfg.resolve("data_external") / "taxonomy"
    target = out_dir / "taxdump.tar.gz"

    print(f"[Taxonomy] {url}")
    download_file(url, target)
    write_manifest(target, source_url=url)

    if args.extract:
        print("  Extraindo nodes.dmp e names.dmp...")
        with tarfile.open(target, "r:gz") as tar:
            for member in ("nodes.dmp", "names.dmp"):
                try:
                    tar.extract(member, path=out_dir)
                    print(f"    {member}")
                except KeyError:
                    print(f"    (ausente: {member})")

    print(f"  Salvo: {target}")


if __name__ == "__main__":
    main()
