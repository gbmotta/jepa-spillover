#!/usr/bin/env bash
# ============================================================
# Executa o pipeline JEPA-Spillover de ponta a ponta.
#
# Uso:
#   bash scripts/run_pipeline.sh            # usa dados reais se existirem; senão, sintéticos
#   DEMO=1 bash scripts/run_pipeline.sh     # força demonstração com dados sintéticos
#   SKIP_TRAIN=1 bash scripts/run_pipeline.sh  # pula o pré-treino JEPA (usa k-mer/PCA)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG="${CONFIG:-$ROOT/config/config.yaml}"
PY="${PYTHON:-python}"
cd "$ROOT"

echo "============================================================"
echo " JEPA-Spillover — pipeline"
echo "============================================================"

step() { echo ""; echo ">>> $*"; }

# 1) Dados: se não houver FASTA baixado, gera dataset sintético
if [[ "${DEMO:-0}" == "1" || -z "$(ls -A data/raw/ncbi_virus/*.fasta 2>/dev/null || true)" ]]; then
    step "Gerando dataset sintético de demonstração"
    "$PY" -m jepa_spillover.cli synth --config "$CONFIG"
fi

step "Curadoria"
"$PY" -m jepa_spillover.cli curate --config "$CONFIG"

step "Representações (k-mers + embeddings)"
"$PY" -m jepa_spillover.cli features --config "$CONFIG"

if [[ "${SKIP_TRAIN:-0}" != "1" ]]; then
    step "Pré-treino JEPA genômica"
    "$PY" -m jepa_spillover.cli train --config "$CONFIG"
else
    echo "(SKIP_TRAIN=1) usando embeddings k-mer/PCA"
fi

step "Fine-tuning supervisionado (risco de spillover)"
"$PY" -m jepa_spillover.cli finetune --config "$CONFIG"

step "Avaliação: UMAP/t-SNE + ranking"
"$PY" -m jepa_spillover.cli evaluate --config "$CONFIG"

echo ""
echo "============================================================"
echo " Concluído. Resultados em results/ e data/processed/."
echo " Visualize com: make dashboard"
echo "============================================================"
