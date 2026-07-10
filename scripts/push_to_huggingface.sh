#!/usr/bin/env bash
# =============================================================================
# JEPA-Spillover — push_to_huggingface.sh
# =============================================================================
# Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
# Módulo  : scripts/push_to_huggingface.sh
#
# Propósito
# ---------
# Publica modelo, dataset ou Space no Hugging Face Hub.
#
# Uso
# ---
#   HF_USER=seu_usuario bash scripts/push_to_huggingface.sh model
#   HF_USER=seu_usuario bash scripts/push_to_huggingface.sh dataset
#   HF_USER=seu_usuario bash scripts/push_to_huggingface.sh space
#
# Requisitos
# ----------
#   pip install -U huggingface_hub
#   hf auth login   OU   export HF_TOKEN=...
#
# Segurança
# ---------
# Não envie sequências GISAID nem secrets.yaml ao Hub.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HF_USER="${HF_USER:-gbmotta}"
REPO_NAME="${REPO_NAME:-jepa-spillover}"
KIND="${1:-model}"   # model | dataset | space
REPO_ID="${HF_USER}/${REPO_NAME}"

if [[ "$HF_USER" == "gbmotta" ]]; then
    echo "Defina HF_USER. Ex.: HF_USER=fulano bash scripts/push_to_huggingface.sh model"
    exit 1
fi

if ! command -v hf >/dev/null 2>&1; then
    echo "CLI 'hf' não encontrada. Instale: pip install -U huggingface_hub"
    exit 1
fi

# Autenticação (usa HF_TOKEN se definido; senão, login interativo prévio)
if [[ -n "${HF_TOKEN:-}" ]]; then
    hf auth login --token "$HF_TOKEN" --add-to-git-credential || true
fi

echo "Criando repo $REPO_ID ($KIND) se não existir..."
hf repo create "$REPO_ID" --repo-type "$KIND" -y || true

case "$KIND" in
  model)
    echo "Enviando checkpoints e cartão do modelo..."
    [[ -f docs/MODEL_CARD.md ]] && hf upload "$REPO_ID" docs/MODEL_CARD.md README.md --repo-type model
    if compgen -G "results/checkpoints/*.pt" >/dev/null; then
        hf upload "$REPO_ID" results/checkpoints --repo-type model
    else
        echo "(sem checkpoints em results/checkpoints — rode 'make train' antes)"
    fi
    ;;
  dataset)
    echo "Enviando dataset processado (sem dados de acesso restrito)..."
    if compgen -G "data/processed/*.parquet" >/dev/null; then
        hf upload "$REPO_ID" data/processed --repo-type dataset --include "*.parquet"
    else
        echo "(sem parquet em data/processed — rode 'make curate' antes)"
    fi
    ;;
  space)
    echo "Para um Space, configure o SDK (gradio/streamlit) e use 'hf upload --repo-type space'."
    ;;
  *)
    echo "Tipo inválido: $KIND (use model | dataset | space)"; exit 1 ;;
esac

echo "Concluído: https://huggingface.co/${KIND}s/${REPO_ID}"
