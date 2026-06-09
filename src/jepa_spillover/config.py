"""Carregamento e acesso à configuração central (config/config.yaml)."""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.yaml"


class Config(dict):
    """Dicionário com acesso por atributo e por caminho pontilhado.

    Exemplo:
        cfg = Config.load()
        cfg.jepa["encoder"]["embed_dim"]
        cfg.get_path("jepa.encoder.embed_dim")
    """

    def __getattr__(self, name: str) -> Any:
        try:
            value = self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
        return Config(value) if isinstance(value, dict) else value

    def get_path(self, dotted: str, default: Any = None) -> Any:
        node: Any = self
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        cfg_path = Path(path) if path else DEFAULT_CONFIG
        with open(cfg_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        cfg = cls(data)
        cfg["_config_path"] = str(cfg_path)
        return cfg

    def resolve(self, key: str) -> Path:
        """Resolve um caminho de `paths` relativo à raiz do projeto."""
        rel = self.get_path(f"paths.{key}")
        if rel is None:
            raise KeyError(f"paths.{key} não definido em config")
        p = PROJECT_ROOT / rel
        return p


def set_global_seed(seed: int) -> None:
    """Fixa seeds para reprodutibilidade (random, numpy, torch se disponível)."""
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def get_device(pref: str = "auto") -> str:
    """Resolve o dispositivo de execução (auto/cpu/cuda)."""
    if pref != "auto":
        return pref
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
