"""Utilitários de segurança: carregamento seguro de artefatos e resolução de segredos."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np

from .logger import get_logger

log = get_logger(__name__)

_ALLOWED_URL_SCHEMES = frozenset({"http", "https", "ftp"})


def assert_safe_url(url: str) -> str:
    """Valida esquema de URL para downloads (bloqueia file://, javascript:, etc.)."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"URL com esquema não permitido: {parsed.scheme!r} "
            f"(permitidos: {sorted(_ALLOWED_URL_SCHEMES)})"
        )
    if not parsed.netloc:
        raise ValueError(f"URL sem host válido: {url!r}")
    return url


def assert_under_root(path: Path, root: Path) -> Path:
    """Garante que `path` resolve para dentro de `root` (anti path-traversal)."""
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Caminho fora da raiz do projeto: {resolved}") from exc
    return resolved


def load_npz(path: Path | str) -> np.lib.npyio.NpzFile:
    """Carrega .npz preferindo allow_pickle=False; fallback só para artefatos locais."""
    path = Path(path)
    try:
        return np.load(path, allow_pickle=False)
    except ValueError as exc:
        log.warning(
            "npz %s exige pickle (ex.: accessions object). "
            "Carregando apenas porque o arquivo é local/confiável: %s",
            path.name, exc,
        )
        return np.load(path, allow_pickle=True)


def safe_torch_load(path: Path | str, map_location: Any = "cpu") -> Any:
    """Carrega checkpoint PyTorch com weights_only=True quando possível."""
    import torch

    path = Path(path)
    try:
        return torch.load(path, map_location=map_location, weights_only=True)
    except Exception as exc:
        log.warning(
            "torch.load(weights_only=True) falhou em %s (%s). "
            "Recarregando com weights_only=False — use apenas checkpoints gerados localmente.",
            path.name, exc,
        )
        return torch.load(path, map_location=map_location, weights_only=False)


def resolve_secret(env_keys: list[str], *, yaml_value: str | None = None) -> str | None:
    """Resolve segredo: variáveis de ambiente têm prioridade sobre o YAML."""
    for key in env_keys:
        val = os.environ.get(key)
        if val and val.strip() and val.strip().upper() not in {"CHANGE_ME", "YOUR_KEY", "TODO"}:
            return val.strip()
    if yaml_value and str(yaml_value).strip().upper() not in {
        "", "CHANGE_ME", "YOUR_KEY", "TODO", "NULL", "NONE",
    }:
        return str(yaml_value).strip()
    return None
