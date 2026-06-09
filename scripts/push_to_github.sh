#!/usr/bin/env bash
# ============================================================
# Sobe o repositório JEPA-Spillover para o GitHub.
#
# Uso:
#   GH_USER=seu_usuario REPO=jepa-spillover bash scripts/push_to_github.sh
#
# Requisitos: git configurado. Opcional: GitHub CLI (`gh`) para criar o repo remoto.
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GH_USER="${GH_USER:-SEU_USUARIO}"
REPO="${REPO:-jepa-spillover}"
BRANCH="${BRANCH:-main}"
REMOTE_URL="${REMOTE_URL:-https://github.com/${GH_USER}/${REPO}.git}"

if [[ "$GH_USER" == "SEU_USUARIO" ]]; then
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
