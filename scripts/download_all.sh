#!/usr/bin/env bash
# =============================================================================
# JEPA-Spillover — download_all.sh
# =============================================================================
# Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
# Módulo  : scripts/download_all.sh
#
# Propósito
# ---------
# Orquestra o download das bases públicas usadas pelo pipeline:
#   1. VirusHostDB (relações vírus–hospedeiro)
#   2. NCBI Taxonomy (taxdump + extração)
#   3. NCBI Virus lote 1 (famílias do config.yaml)
#
# Falhas individuais NÃO abortam o script (continuam com aviso), para permitir
# downloads parciais em redes instáveis.
#
# Uso
# ---
#   bash scripts/download_all.sh
#   bash scripts/download_all.sh config/config.yaml
#   PYTHON=python3 bash scripts/download_all.sh
#
# Pré-requisitos
# --------------
# - E-mail Entrez e (recomendado) NCBI_API_KEY em config/secrets.yaml
# - GISAID / VirHostNet: download manual (ver docs/data_sources.md)
#
# =============================================================================
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
echo "Lote 2 (famílias extras): python scripts/download_ncbi_batch2.py"
echo "Veja docs/data_sources.md."
echo "Concluído."
