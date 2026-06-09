#!/usr/bin/env bash
# ============================================================
# Baixa todas as bases públicas usadas pelo JEPA-Spillover.
# Uso: bash scripts/download_all.sh [config.yaml]
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${1:-$SCRIPT_DIR/../config/config.yaml}"
PY="${PYTHON:-python}"

echo "============================================================"
echo " JEPA-Spillover — download de bases públicas"
echo " Config: $CONFIG"
echo "============================================================"

run() {
    echo ""
    echo ">>> $1"
    if "$PY" "$SCRIPT_DIR/$1" --config "$CONFIG" "${@:2}"; then
        echo "    OK"
    else
        echo "    FALHOU (continuando): $1" >&2
    fi
}

# Bases de acesso direto
run download_virushostdb.py
run download_taxonomy.py --extract

# NCBI Virus (exige e-mail configurado)
run download_ncbi_virus.py

echo ""
echo "Lembrete: VirHostNet e GISAID exigem download manual/credenciamento."
echo "Veja docs/data_sources.md."
echo "Concluído."
