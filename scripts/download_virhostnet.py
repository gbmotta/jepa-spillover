#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
JEPA-Spillover — download VirHostNet 3.0 (PSI-MITAB)
=============================================================================
Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
Módulo  : scripts/download_virhostnet.py

Propósito
---------
Obtém interações vírus–hospedeiro via PSICQUIC (endpoint oficial → mirror
Lyon → NDEx), em formato PSI-MITAB 2.5.

Saídas
------
- ``data/external/virhostnet/virhostnet.mitab``
- ``data/external/virhostnet/virhostnet.parquet``

Uso
---
    python scripts/download_virhostnet.py
    python scripts/download_virhostnet.py --max-rows 50000 --debug

Notas
-----
Endpoints externos podem ficar offline; o script tenta fallbacks em ordem.
=============================================================================
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from jepa_spillover.logger import get_logger

log = get_logger("scripts.virhostnet")

# ── Endpoints ────────────────────────────────────────────────────────────────
PSICQUIC_BASE   = "http://virhostnet.prabi.fr:9090/psicquic/webservices/current/search/query"
PSICQUIC_MIRROR = "http://virhostnet.univ-lyon1.fr:9090/psicquic/webservices/current/search/query"

# NDEx: VirHostNet network UUID (público)
NDEX_UUID    = "2d2b4b7a-2a7c-11e8-b939-0ac135e8bacf"
NDEX_API     = f"https://www.ndexbio.org/v2/network/{NDEX_UUID}/export?download=true&format=MITAB"

MITAB_COLS = [
    "idA", "idB", "altA", "altB", "aliasA", "aliasB",
    "method", "authors", "pmid", "taxA", "taxB",
    "type", "source", "identifier", "confidence",
]

OUT_DIR = Path("data/external/virhostnet")


# ── Download PSICQUIC com paginação ──────────────────────────────────────────

def download_psicquic(base_url: str, max_rows: int, timeout: int = 30) -> list[str]:
    """Baixa via PSICQUIC REST com paginação de 1000 linhas."""
    # Contar total primeiro
    count_url = f"{base_url}/*?format=count"
    try:
        r = requests.get(count_url, timeout=timeout)
        r.raise_for_status()
        total = int(r.text.strip())
        log.info("PSICQUIC: %d interações disponíveis", total)
    except Exception as e:
        log.warning("Não foi possível obter contagem: %s", e)
        total = max_rows

    total = min(total, max_rows)
    page_size = 1000
    lines: list[str] = []

    with tqdm(total=total, desc="PSICQUIC download", unit="int") as bar:
        for first in range(0, total, page_size):
            url = f"{base_url}/*?format=tab25&firstResult={first}&maxResults={page_size}"
            try:
                r = requests.get(url, timeout=timeout)
                r.raise_for_status()
                batch = [l for l in r.text.splitlines() if l and not l.startswith("#")]
                lines.extend(batch)
                bar.update(len(batch))
                if len(batch) < page_size:
                    break
                time.sleep(0.2)
            except requests.exceptions.ConnectionError as e:
                log.error("Conexão recusada (porta bloqueada?): %s", e)
                return []
            except Exception as e:
                log.error("Erro na página %d: %s", first, e)
                break

    return lines


def download_ndex(timeout: int = 60) -> list[str]:
    """Baixa via NDEx API como MITAB."""
    log.info("Tentando NDEx API: %s", NDEX_API)
    try:
        r = requests.get(NDEX_API, timeout=timeout, stream=True)
        r.raise_for_status()
        lines = []
        for line in r.iter_lines():
            if line:
                decoded = line.decode("utf-8") if isinstance(line, bytes) else line
                if not decoded.startswith("#"):
                    lines.append(decoded)
        log.info("NDEx: %d linhas baixadas", len(lines))
        return lines
    except Exception as e:
        log.error("NDEx falhou: %s", e)
        return []


def parse_mitab(lines: list[str]) -> pd.DataFrame:
    """Converte linhas MITAB 2.5 em DataFrame."""
    if not lines:
        return pd.DataFrame()
    from io import StringIO
    text = "\n".join(lines)
    df = pd.read_csv(
        StringIO(text),
        sep="\t",
        header=None,
        names=MITAB_COLS[:15],
        on_bad_lines="skip",
        dtype=str,
    )
    # Extrair taxon IDs limpos (ex: "taxid:9606(Homo sapiens)" → "9606")
    for col in ["taxA", "taxB"]:
        if col in df.columns:
            df[col + "_id"] = df[col].str.extract(r"taxid:(\d+)", expand=False)
    # Flag: interação vírus-hospedeiro (taxons diferentes)
    if "taxA_id" in df.columns and "taxB_id" in df.columns:
        df["is_virus_host"] = df["taxA_id"] != df["taxB_id"]
    log.info("MITAB parseado: %d interações", len(df))
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-rows", type=int, default=200_000)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=str, default=str(OUT_DIR))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.debug:
        import os
        os.environ["JEPA_LOG_LEVEL"] = "DEBUG"
        from jepa_spillover.logger import set_log_level
        set_log_level("DEBUG")

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    # Tentativa 1: PSICQUIC oficial
    log.info("Tentativa 1: PSICQUIC oficial (%s)", PSICQUIC_BASE)
    lines = download_psicquic(PSICQUIC_BASE, args.max_rows, args.timeout)

    # Tentativa 2: Mirror Lyon
    if not lines:
        log.info("Tentativa 2: Mirror Lyon (%s)", PSICQUIC_MIRROR)
        lines = download_psicquic(PSICQUIC_MIRROR, args.max_rows, args.timeout)

    # Tentativa 3: NDEx
    if not lines:
        log.info("Tentativa 3: NDEx API")
        lines = download_ndex(timeout=60)

    if not lines:
        log.error(
            "Todas as tentativas falharam.\n"
            "Download manual:\n"
            "  1. Acesse https://virhostnet.prabi.fr\n"
            "  2. Tente abrir: http://virhostnet.prabi.fr:9090/psicquic/webservices/current/search/query/*\n"
            "  3. Salve como: %s/virhostnet.mitab",
            out,
        )
        sys.exit(1)

    # Salvar MITAB bruto
    mitab_path = out / "virhostnet.mitab"
    mitab_path.write_text("\n".join(lines))
    log.info("MITAB salvo: %s (%d linhas)", mitab_path, len(lines))

    # Converter para Parquet
    df = parse_mitab(lines)
    if not df.empty:
        parquet_path = out / "virhostnet.parquet"
        df.to_parquet(parquet_path, index=False)
        log.info("Parquet salvo: %s — shape %s", parquet_path, df.shape)
        if "is_virus_host" in df.columns:
            vh = df["is_virus_host"].sum()
            log.info("Interações vírus-hospedeiro: %d / %d", vh, len(df))


if __name__ == "__main__":
    main()
