"""Utilidades compartilhadas pelos scripts de download."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# Permite importar o pacote sem instalação (`pip install -e .`)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def write_manifest(target: Path, *, source_url: str, n_records: int | None = None, **extra) -> Path:
    """Grava um manifesto JSON ao lado do arquivo baixado."""
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
    return manifest_path


def download_file(url: str, target: Path, *, chunk: int = 1 << 16, timeout: int = 120) -> Path:
    """Baixa um arquivo grande em streaming com barra de progresso simples."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = 0
        with open(target, "wb") as fh:
            for block in resp.iter_content(chunk_size=chunk):
                fh.write(block)
                done += len(block)
                if total:
                    pct = 100 * done / total
                    print(f"\r  {target.name}: {pct:5.1f}% ({done/1e6:.1f} MB)", end="", flush=True)
        print()
    return target
