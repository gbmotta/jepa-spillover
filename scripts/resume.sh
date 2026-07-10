#!/usr/bin/env bash
# =============================================================================
# JEPA-Spillover — resume.sh
# =============================================================================
# Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
# Módulo  : scripts/resume.sh
#
# Propósito
# ---------
# Retoma o pipeline após reinício do PC (ou inicia do zero):
#   1. Verifica GPU / CUDA
#   2. Detecta checkpoint intermediário (jepa_genomic_latest.pt) ou final
#   3. train → features → finetune → evaluate → validate_biology
#   4. (Opcional) upload do dashboard para Hugging Face Space
#   5. (Opcional) git commit de artefatos de resultados
#
# Uso
# ---
#   bash scripts/resume.sh
#
# Requisitos
# ----------
# - Pacote instalado (`pip install -e .`) para o comando `jepa-spillover`
# - Token HF opcional em ~/Documentos/huggin_token.txt
#
# Segurança
# ---------
# Não imprima o token HF em logs compartilhados. O arquivo de token deve
# permanecer fora do repositório.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
info() { echo -e "ℹ️  $*"; }

echo "=================================================="
echo "  JEPA-Spillover — Retomada de pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="

# ── 1. GPU ─────────────────────────────────────────────────────────────────
info "Verificando GPU..."
if python3 -c "import torch; assert torch.cuda.is_available(), 'CUDA indisponível'" 2>/dev/null; then
    GPU=$(python3 -c "import torch; print(torch.cuda.get_device_name(0))")
    ok "GPU disponível: $GPU"
else
    warn "GPU não disponível — treino rodará na CPU (muito mais lento)"
fi

# ── 2. Checkpoint ──────────────────────────────────────────────────────────
CKPT_LATEST="$ROOT/results/checkpoints/jepa_genomic_latest.pt"
CKPT_FINAL="$ROOT/results/checkpoints/jepa_genomic.pt"

if [[ -f "$CKPT_LATEST" ]]; then
    EPOCH=$(python3 -c "
import torch
d = torch.load('$CKPT_LATEST', map_location='cpu', weights_only=False)
print(d.get('epoch', '?'))
" 2>/dev/null || echo "?")
    ok "Checkpoint intermediário encontrado — retomando da época $EPOCH"
elif [[ -f "$CKPT_FINAL" ]]; then
    warn "Apenas checkpoint final encontrado (sem época salva) — treino iniciará do zero"
else
    info "Nenhum checkpoint — treino iniciará do zero (~3h20min na GPU)"
fi

# ── 3. Pré-treino JEPA ────────────────────────────────────────────────────
info "Iniciando/retomando pré-treino JEPA..."
info "(Salva checkpoint a cada 5 épocas — pode interromper e retomar com segurança)"
echo ""

jepa-spillover train
ok "Pré-treino JEPA concluído!"

# ── 4. Gerar embeddings ───────────────────────────────────────────────────
info "Gerando embeddings JEPA..."
jepa-spillover features
ok "Embeddings gerados."

# ── 5. Fine-tuning ────────────────────────────────────────────────────────
info "Rodando fine-tuning supervisionado..."
jepa-spillover finetune
ok "Fine-tuning concluído."

# ── 6. Avaliação ──────────────────────────────────────────────────────────
info "Rodando avaliação (UMAP vs t-SNE + ranking)..."
jepa-spillover evaluate
ok "Avaliação concluída."

# ── 7. Validação biológica ────────────────────────────────────────────────
info "Rodando validação biológica..."
python3 scripts/validate_biology.py
ok "Validação concluída."

# ── 8. Upload HF Space ────────────────────────────────────────────────────
TOKEN_FILE="$HOME/Documentos/huggin_token.txt"
if [[ -f "$TOKEN_FILE" ]]; then
    info "Fazendo upload para Hugging Face Space..."
    TOKEN=$(cat "$TOKEN_FILE" | tr -d '[:space:]')
    python3 - <<PYEOF
from huggingface_hub import HfApi, login
from pathlib import Path
import pandas as pd, tempfile, os

login(token="$TOKEN", add_to_git_credential=False)
api = HfApi()
REPO = "gbmotta/jepa-spillover-dashboard"
ROOT = Path("$ROOT")

df = pd.read_parquet(ROOT / "data" / "processed" / "dataset.parquet")
df_slim = df.drop(columns=["sequence"], errors="ignore")
tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
df_slim.to_parquet(tmp.name, index=False)

uploads = [
    (tmp.name,                                                           "data/processed/dataset.parquet"),
    (ROOT / "data" / "processed" / "latent_2d.parquet",                "data/processed/latent_2d.parquet"),
    (ROOT / "results" / "metrics" / "finetune_metrics.json",           "results/metrics/finetune_metrics.json"),
    (ROOT / "results" / "rankings" / "virus_priority_ranking.csv",     "results/rankings/virus_priority_ranking.csv"),
    (ROOT / "results" / "figures" / "latent_by_family.png",            "results/figures/latent_by_family.png"),
    (ROOT / "results" / "figures" / "latent_by_spillover.png",         "results/figures/latent_by_spillover.png"),
    (ROOT / "results" / "figures" / "reducer_comparison.png",          "results/figures/reducer_comparison.png"),
    (ROOT / "results" / "kmer_sweep_full" / "kmer_sweep_results.json", "results/kmer_sweep_full/kmer_sweep_results.json"),
    (ROOT / "results" / "kmer_sweep_full" / "kmer_sweep.png",          "results/kmer_sweep_full/kmer_sweep.png"),
]
for local, remote in uploads:
    local = Path(local)
    if local.exists():
        print(f"  {remote}...", end=" ", flush=True)
        try:
            api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                            repo_id=REPO, repo_type="space")
            print("OK")
        except Exception as e:
            print(f"ERRO: {e}")
os.unlink(tmp.name)
PYEOF
    ok "HF Space atualizado."
else
    warn "Token HF não encontrado — pulando upload."
fi

# ── 9. Git commit ─────────────────────────────────────────────────────────
git add results/ data/processed/latent_2d.parquet 2>/dev/null || true
git commit -m "feat: resultados pós-JEPA — embeddings + métricas + UMAP vs t-SNE" \
    --allow-empty 2>/dev/null && ok "Git commit OK." || info "Nada novo para commitar."

echo ""
echo "=================================================="
ok "Pipeline completo! Verifique o dashboard:"
echo "   https://huggingface.co/spaces/gbmotta/jepa-spillover-dashboard"
echo "=================================================="
