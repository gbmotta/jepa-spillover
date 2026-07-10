"""Configuração centralizada de logging para o JEPA-Spillover.

Uso:
    from jepa_spillover.logger import get_logger, set_log_level
    log = get_logger(__name__)
    log.info("mensagem")
    log.debug("detalhe")

O nível é controlado pela variável de ambiente JEPA_LOG_LEVEL (default: INFO).
Um arquivo de log rotativo é criado em logs/jepa_spillover.log.

Para ativar DEBUG depois do import (ex.: --debug na CLI):
    set_log_level("DEBUG")
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

_LOG_LEVEL = os.environ.get("JEPA_LOG_LEVEL", "INFO").upper()
_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_FILE = _LOG_DIR / "jepa_spillover.log"
_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_initialized = False


def _setup() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("jepa_spillover")
    root.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))
    root.propagate = False

    if not root.handlers:
        # Console — colorido por nível
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(_ColorFormatter(_FMT, _DATE_FMT))
        console.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))
        root.addHandler(console)

        # Arquivo rotativo (5 MB × 3 backups)
        try:
            fh = logging.handlers.RotatingFileHandler(
                _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            fh.setFormatter(logging.Formatter(_FMT, _DATE_FMT))
            fh.setLevel(logging.DEBUG)
            root.addHandler(fh)
        except OSError:
            pass  # filesystem read-only (ex.: CI/CD)


def set_log_level(level: str) -> None:
    """Atualiza o nível de log em runtime (útil para --debug após imports)."""
    global _LOG_LEVEL
    _LOG_LEVEL = level.upper()
    os.environ["JEPA_LOG_LEVEL"] = _LOG_LEVEL
    lvl = getattr(logging, _LOG_LEVEL, logging.INFO)
    _setup()
    root = logging.getLogger("jepa_spillover")
    root.setLevel(lvl)
    for handler in root.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            continue  # arquivo permanece em DEBUG
        handler.setLevel(lvl)


class _ColorFormatter(logging.Formatter):
    _COLORS = {
        "DEBUG":    "\033[36m",   # ciano
        "INFO":     "\033[32m",   # verde
        "WARNING":  "\033[33m",   # amarelo
        "ERROR":    "\033[31m",   # vermelho
        "CRITICAL": "\033[35m",   # magenta
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self._RESET}"
        return super().format(record)


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger filho do namespace jepa_spillover."""
    _setup()
    if not name.startswith("jepa_spillover"):
        name = f"jepa_spillover.{name}"
    return logging.getLogger(name)
