#!/usr/bin/env bash
# =============================================================================
# JEPA-Spillover — push_to_github.sh
# =============================================================================
# Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
# Módulo  : scripts/push_to_github.sh
#
# Propósito
# ---------
# Inicializa (se necessário) e publica o repositório no GitHub.
#
# Uso
# ---
#   GH_USER=seu_usuario REPO=jepa-spillover bash scripts/push_to_github.sh
#
# Variáveis
# ---------
#   GH_USER, REPO, BRANCH, REMOTE_URL
#
# Requisitos
# ----------
#   git; opcionalmente GitHub CLI (`gh`) para criar o remoto.
#
# Segurança
# ---------
# Não faça commit de config/secrets.yaml, tokens ou dados GISAID.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GH_USER="${GH_USER:-gbmotta}"
REPO="${REPO:-jepa-spillover}"
BRANCH="${BRANCH:-main}"
REMOTE_URL="${REMOTE_URL:-https://github.com/${GH_USER}/${REPO}.git}"

if [[ "$GH_USER" == "gbmotta" ]]; then
    echo "Defina GH_USER (e opcionalmente REPO). Ex.:"
    echo "  GH_USER=fulano REPO=jepa-spillover bash scripts/push_to_github.sh"
    exit 1
fi

# Inicializa o repositório local, se necessário
if [[ ! -d .git ]]; then
    git init
    git branch -M "$BRANCH"
fi

git add -A
git commit -m "JEPA-Spillover: estrutura, pipeline, docs, dashboard e apresentação" || echo "(nada novo para commitar)"

# Cria o repositório remoto via GitHub CLI, se disponível
if command -v gh >/dev/null 2>&1; then
    gh repo view "${GH_USER}/${REPO}" >/dev/null 2>&1 || \
        gh repo create "${GH_USER}/${REPO}" --public --source=. --remote=origin --push
fi

# Garante o remote 'origin'
if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "$REMOTE_URL"
fi

git push -u origin "$BRANCH"
echo "Enviado para $REMOTE_URL ($BRANCH)"
