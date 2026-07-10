#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
JEPA-Spillover — download NCBI Taxonomy (taxdump)
=============================================================================
Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
Módulo  : scripts/download_taxonomy.py

Propósito
---------
Baixa ``taxdump.tar.gz`` do NCBI e, opcionalmente, extrai ``nodes.dmp`` e
``names.dmp`` para padronização taxonômica na curadoria.

Segurança
---------
Extração com filtro anti path-traversal (apenas nomes basenames permitidos;
``filter="data"`` em Python ≥ 3.12).

Uso
---
    python scripts/download_taxonomy.py --config config/config.yaml --extract
    python scripts/download_taxonomy.py --debug
=============================================================================
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
    """CLI: download taxdump e, se ``--extract``, extrai nodes/names.dmp com segurança."""
    parser = argparse.ArgumentParser(description="Download do NCBI Taxonomy (taxdump)")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    parser.add_argument("--extract", action="store_true", help="Extrai nodes.dmp/names.dmp")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        import os
        os.environ["JEPA_LOG_LEVEL"] = "DEBUG"
        from jepa_spillover.logger import set_log_level
        set_log_level("DEBUG")


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
            extract_kw = {"path": out_dir}
            # Python 3.12+: filter="data" mitiga path traversal
            import inspect
            if "filter" in inspect.signature(tar.extract).parameters:
                extract_kw["filter"] = "data"
            for member in tqdm(members, desc="Extraindo", unit="arquivo", ncols=90):
                # Bloqueia path traversal mesmo em Pythons antigos
                if Path(member.name).name != member.name or ".." in member.name:
                    log.warning("Membro tar suspeito ignorado: %s", member.name)
                    continue
                tar.extract(member, **extract_kw)
                log.debug("Extraído: %s (%.1f MB)", member.name, member.size / 1e6)
        log.info("Extração concluída em %s", out_dir)

    log.info("Taxonomy concluído: %s", target)


if __name__ == "__main__":
    main()
