#!/usr/bin/env python
"""Baixa genomas virais do NCBI (Entrez) por família, com metadados.

Uso:
    python scripts/download_ncbi_virus.py --config config/config.yaml
    python scripts/download_ncbi_virus.py --family Coronaviridae --max 200

Requer e-mail válido em `config.yaml → data_sources.ncbi_virus.email`
(exigência da política de uso da API Entrez do NCBI).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from _utils import PROJECT_ROOT, write_manifest

from jepa_spillover.config import Config


def fetch_family(entrez, family: str, *, min_length: int, max_records: int):
    """Busca e baixa sequências de uma família viral via Entrez."""
    query = f'"{family}"[Organism] AND {min_length}:99999999[Sequence Length]'
    handle = entrez.esearch(db="nuccore", term=query, retmax=max_records, idtype="acc")
    record = entrez.read(handle)
    handle.close()
    ids = record["IdList"]
    if not ids:
        return ""

    fasta_chunks = []
    batch = 200
    for start in range(0, len(ids), batch):
        subset = ids[start : start + batch]
        fetch = entrez.efetch(db="nuccore", id=",".join(subset), rettype="fasta", retmode="text")
        fasta_chunks.append(fetch.read())
        fetch.close()
        time.sleep(0.34)  # respeita o limite de ~3 req/s sem API key
        print(f"    {family}: {min(start + batch, len(ids))}/{len(ids)}")
    return "".join(fasta_chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download de genomas virais do NCBI Virus")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.yaml"))
    parser.add_argument("--family", action="append", help="Restringe a uma ou mais famílias")
    parser.add_argument("--max", type=int, default=None, help="Máx. de registros por família")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    src = cfg.get_path("data_sources.ncbi_virus", {})
    email = src.get("email")
    if not email or "exemplo.org" in email:
        raise SystemExit(
            "Defina um e-mail real em config.yaml → data_sources.ncbi_virus.email "
            "(exigido pela API Entrez do NCBI)."
        )

    try:
        from Bio import Entrez
    except ImportError as exc:
        raise SystemExit("Biopython é necessário: pip install biopython") from exc

    Entrez.email = email
    if src.get("api_key"):
        Entrez.api_key = src["api_key"]

    families = args.family or src.get("families", [])
    min_length = int(src.get("min_length", 1000))
    max_records = int(args.max or src.get("max_records_per_family", 5000))

    out_dir = cfg.resolve("data_raw") / "ncbi_virus"
    out_dir.mkdir(parents=True, exist_ok=True)

    for family in families:
        print(f"[NCBI] {family} (min_len={min_length}, max={max_records})")
        fasta = fetch_family(Entrez, family, min_length=min_length, max_records=max_records)
        if not fasta.strip():
            print(f"  Nenhuma sequência encontrada para {family}.")
            continue
        target = out_dir / f"{family}.fasta"
        target.write_text(fasta, encoding="utf-8")
        n = fasta.count(">")
        write_manifest(
            target,
            source_url=f"https://www.ncbi.nlm.nih.gov/nuccore/?term={family}",
            n_records=n,
            family=family,
            min_length=min_length,
        )
        print(f"  Salvo: {target} ({n} sequências)")

    print("Concluído. FASTA em", out_dir)


if __name__ == "__main__":
    main()
