#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
JEPA-Spillover — utilidades compartilhadas dos scripts de download
=============================================================================
Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
Módulo  : scripts/_utils.py

Propósito
---------
Funções comuns a todos os scripts de coleta de dados externos:
  - download HTTP(S)/FTP com barra tqdm e timeout;
  - checksum SHA-256 com progresso;
  - manifesto JSON de proveniência (reprodutibilidade / auditoria).

Segurança
---------
- URLs validadas via ``jepa_spillover.security.assert_safe_url``
  (apenas esquemas http, https, ftp).
- Timeouts explícitos em requests (evita hang indefinido).

Uso (importado pelos demais scripts)
------------------------------------
    from _utils import PROJECT_ROOT, download_file, write_manifest, sha256_of

Variáveis de ambiente
---------------------
    JEPA_LOG_LEVEL  — INFO (default) | DEBUG | WARNING | ERROR

=============================================================================
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jepa_spillover.logger import get_logger  # noqa: E402

log = get_logger("scripts.utils")


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    """Calcula SHA-256 de um arquivo em streaming (não carrega tudo na RAM).

    Parameters
    ----------
    path :
        Arquivo local existente.
    chunk :
        Tamanho do bloco de leitura em bytes (default 1 MiB).

    Returns
    -------
    str
        Digest hexadecimal de 64 caracteres.
    """
    h = hashlib.sha256()
    total = path.stat().st_size
    with open(path, "rb") as fh:
        with tqdm(total=total, unit="B", unit_scale=True,
                  desc=f"checksum {path.name}", leave=False) as bar:
            while block := fh.read(chunk):
                h.update(block)
                bar.update(len(block))
    return h.hexdigest()


def write_manifest(target: Path, *, source_url: str, n_records: int | None = None, **extra) -> Path:
    """Grava manifesto JSON ao lado do arquivo baixado (proveniência).

    O manifesto inclui URL de origem, timestamp UTC, tamanho, SHA-256 e
    metadados extras (família viral, batch, etc.). Essencial para auditoria
    e para saber se um re-download é necessário.

    Parameters
    ----------
    target :
        Arquivo de dados (ex.: ``Coronaviridae.fasta``).
    source_url :
        URL canônica de origem.
    n_records :
        Número de registros (ex.: sequências FASTA), se conhecido.
    **extra :
        Campos adicionais serializados no JSON.

    Returns
    -------
    Path
        Caminho do manifesto (``<arquivo>.manifest.json``).
    """
    manifest = {
        "file": target.name,
        "source_url": source_url,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "size_bytes": target.stat().st_size if target.exists() else None,
        "sha256": sha256_of(target) if target.exists() else None,
        "n_records": n_records,
        **extra,
    }
    manifest_path = target.with_suffix(target.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log.debug("Manifesto gravado: %s", manifest_path)
    return manifest_path


def download_file(url: str, target: Path, *, chunk: int = 1 << 16, timeout: int = 120) -> Path:
    """Baixa um arquivo em streaming com barra de progresso tqdm.

    Parameters
    ----------
    url :
        URL http(s)/ftp (outros esquemas são rejeitados).
    target :
        Caminho de destino local.
    chunk :
        Tamanho do bloco de escrita.
    timeout :
        Timeout total da conexão/leitura em segundos.

    Returns
    -------
    Path
        O mesmo ``target``, após download bem-sucedido.

    Raises
    ------
    ValueError
        Se o esquema da URL for inválido.
    requests.HTTPError
        Se a resposta HTTP não for 2xx.
    """
    from jepa_spillover.security import assert_safe_url

    assert_safe_url(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    log.info("Iniciando download: %s → %s", url, target)

    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0)) or None
        with tqdm(total=total, unit="B", unit_scale=True,
                  desc=target.name, ncols=90) as bar:
            with open(target, "wb") as fh:
                for block in resp.iter_content(chunk_size=chunk):
                    fh.write(block)
                    bar.update(len(block))

    size_mb = target.stat().st_size / 1e6
    log.info("Download concluído: %s (%.1f MB)", target.name, size_mb)
    return target
