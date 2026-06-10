#!/usr/bin/env python
"""Baixa e extrai o taxdump do NCBI Taxonomy.

Uso:
    python scripts/download_taxonomy.py --config config/config.yaml --extract
"""

from __future__ import annotations

import argparse
import tarfile

from _utils import PROJECT_ROOT, download_file, write_manifest
from tqdm import tqdm

from jepa_spillover.config import Config
from jepa_spillover.logger import get_logger

log = get_logger("scripts.download_taxonomy")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download do NCBI Taxonomy (taxdump)")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    parser.add_argument("--extract", action="store_true", help="Extrai nodes.dmp/names.dmp")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        import os; os.environ["JEPA_LOG_LEVEL"] = "DEBUG"

    cfg = Config.load(args.config)
    url = cfg.get_path(
        "data_sources.taxonomy.ncbi_taxdump",
        "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz",
    )
    out_dir = cfg.resolve("data_external") / "taxonomy"
    target = out_dir / "taxdump.tar.gz"

    log.info("NCBI Taxonomy → %s", target)
    download_file(url, target)
    write_manifest(target, source_url=url)

    if args.extract:
        log.info("Extraindo nodes.dmp e names.dmp...")
        with tarfile.open(target, "r:gz") as tar:
            members = [m for m in tar.getmembers() if m.name in ("nodes.dmp", "names.dmp")]
            for member in tqdm(members, desc="Extraindo", unit="arquivo", ncols=90):
                tar.extract(member, path=out_dir)
                log.debug("Extraído: %s (%.1f MB)", member.name, member.size / 1e6)
        log.info("Extração concluída em %s", out_dir)

    log.info("Taxonomy concluído: %s", target)


if __name__ == "__main__":
    main()
