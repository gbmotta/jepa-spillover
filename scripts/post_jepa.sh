#!/usr/bin/env bash
# =============================================================================
# JEPA-Spillover — post_jepa.sh
# =============================================================================
# Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
# Módulo  : scripts/post_jepa.sh
#
# Propósito
# ---------
# Monitora um processo de pré-treino JEPA em andamento e, ao terminar,
# executa automaticamente: features → finetune → evaluate (+ métricas / HF).
#
# Uso
# ---
#   bash scripts/post_jepa.sh              # detecta PID automaticamente
#   bash scripts/post_jepa.sh <JEPA_PID>   # PID explícito do python train
#
# Logs
# ----
#   results/post_jepa.log
#
# Nota
# ----
# Prefira passar o PID do processo ``python -m jepa_spillover.cli train``
# (não o shell wrapper). Alternativa moderna: o watcher em
# logs/post_train_pipeline.log iniciado junto com o treino.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/results/post_jepa.log"
TOKEN_FILE="$HOME/Documentos/huggin_token.txt"
HF_SPACE="gbmotta/jepa-spillover-dashboard"

mkdir -p "$ROOT/results"
exec > >(tee -a "$LOG") 2>&1

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

log_info()  { echo "$(timestamp) | INFO  | $*"; }
log_ok()    { echo "$(timestamp) | OK    | $*"; }
log_err()   { echo "$(timestamp) | ERROR | $*"; exit 1; }

log_info "=== post_jepa.sh iniciado ==="

# ── 1. Detectar PID do treino JEPA ──────────────────────────────────────────
JEPA_PID="${1:-}"
if [[ -z "$JEPA_PID" ]]; then
    JEPA_PID=$(pgrep -f "jepa-spillover train" | head -1 || true)
fi

if [[ -z "$JEPA_PID" ]]; then
    log_info "Nenhum processo jepa-spillover train em execução — rodando pipeline imediatamente."
else
    log_info "Monitorando PID $JEPA_PID (jepa-spillover train)..."
    # Aguardar processo terminar verificando a cada 60s
    while kill -0 "$JEPA_PID" 2>/dev/null; do
        CKPT="$ROOT/results/checkpoints/jepa_genomic.pt"
        if [[ -f "$CKPT" ]]; then
            AGE=$(( $(date +%s) - $(stat -c %Y "$CKPT") ))
            log_info "Treino em andamento... (checkpoint há ${AGE}s | PID $JEPA_PID ativo)"
        else
            log_info "Aguardando checkpoint... (PID $JEPA_PID ativo)"
        fi
        sleep 60
    done
    log_ok "Processo $JEPA_PID encerrado — treino JEPA concluído!"
fi

# ── 2. Verificar checkpoint ──────────────────────────────────────────────────
CKPT="$ROOT/results/checkpoints/jepa_genomic.pt"
if [[ ! -f "$CKPT" ]]; then
    log_err "Checkpoint não encontrado em $CKPT — treino pode ter falhado."
fi
CKPT_AGE=$(( $(date +%s) - $(stat -c %Y "$CKPT") ))
log_ok "Checkpoint encontrado (modificado há ${CKPT_AGE}s): $CKPT"

# ── 3. Gerar embeddings JEPA ─────────────────────────────────────────────────
log_info "Gerando embeddings JEPA (jepa-spillover features)..."
cd "$ROOT"
jepa-spillover features && log_ok "Embeddings gerados." || log_err "Falha em features."

# ── 4. Fine-tuning com embeddings JEPA ──────────────────────────────────────
log_info "Rodando fine-tuning supervisionado..."
jepa-spillover finetune && log_ok "Fine-tuning concluído." || log_err "Falha em finetune."

# ── 5. Evaluate: UMAP vs t-SNE + ranking ────────────────────────────────────
log_info "Rodando evaluate (UMAP vs t-SNE + ranking)..."
jepa-spillover evaluate && log_ok "Evaluate concluído." || log_err "Falha em evaluate."

# ── 6. Mostrar métricas finais ───────────────────────────────────────────────
log_info "=== RESULTADOS FINAIS ==="
python3 - <<'PYEOF'
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent if "__file__" in dir() else Path(".")
metrics_path = root / "results" / "metrics" / "finetune_metrics.json"
reducer_path = root / "results" / "figures" / "reducer_comparison.json"

if metrics_path.exists():
    m = json.loads(metrics_path.read_text())
    cv = m.get("cv", {})
    cf = m.get("cross_family", {})
    print(f"  AUROC (CV):          {cv.get('auroc', 'N/A'):.4f}")
    print(f"  AUPRC (CV):          {cv.get('auprc', 'N/A'):.4f}")
    print(f"  F1 (CV):             {cv.get('f1', 'N/A'):.4f}")
    print(f"  Especificidade (CV): {cv.get('specificity', 'N/A'):.4f}")
    print(f"  AUROC cross-família: {cf.get('auroc', 'N/A')}")

if reducer_path.exists():
    r = json.loads(reducer_path.read_text())
    print(f"  Melhor redutor: {r.get('best','?').upper()}")
    for red in ("umap", "tsne"):
        if red in r:
            print(f"    {red.upper()}: silhouette={r[red]['silhouette']:.4f} ({r[red]['time_s']}s)")
PYEOF

# ── 7. Atualizar Hugging Face Space ─────────────────────────────────────────
if [[ ! -f "$TOKEN_FILE" ]]; then
    log_info "Token HF não encontrado em $TOKEN_FILE — pulando upload."
else
    log_info "Fazendo upload para HF Space ($HF_SPACE)..."
    TOKEN=$(cat "$TOKEN_FILE" | tr -d '[:space:]')

    python3 - <<PYEOF
import sys
from pathlib import Path
from huggingface_hub import HfApi, login

login(token="$TOKEN", add_to_git_credential=False)
api = HfApi()
REPO = "$HF_SPACE"
ROOT = Path("$ROOT")

# Dataset sem sequence (slim)
import pandas as pd, tempfile, os
df = pd.read_parquet(ROOT / "data" / "processed" / "dataset.parquet")
df_slim = df.drop(columns=["sequence"], errors="ignore")
tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
df_slim.to_parquet(tmp.name, index=False)

uploads = [
    (tmp.name,                                                          "data/processed/dataset.parquet"),
    (ROOT / "data" / "processed" / "latent_2d.parquet",               "data/processed/latent_2d.parquet"),
    (ROOT / "results" / "metrics" / "finetune_metrics.json",          "results/metrics/finetune_metrics.json"),
    (ROOT / "results" / "rankings" / "virus_priority_ranking.csv",    "results/rankings/virus_priority_ranking.csv"),
    (ROOT / "results" / "figures" / "latent_by_family.png",           "results/figures/latent_by_family.png"),
    (ROOT / "results" / "figures" / "latent_by_spillover.png",        "results/figures/latent_by_spillover.png"),
    (ROOT / "results" / "figures" / "reducer_comparison.png",         "results/figures/reducer_comparison.png"),
    (ROOT / "results" / "kmer_sweep_full" / "kmer_sweep_results.json","results/kmer_sweep_full/kmer_sweep_results.json"),
    (ROOT / "results" / "kmer_sweep_full" / "kmer_sweep.png",         "results/kmer_sweep_full/kmer_sweep.png"),
]

for local, remote in uploads:
    local = Path(local)
    if local.exists():
        print(f"  Enviando {remote}...", end=" ", flush=True)
        try:
            api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                            repo_id=REPO, repo_type="space")
            print("OK")
        except Exception as e:
            print(f"ERRO: {e}")
    else:
        print(f"  Pulando {remote} (arquivo não encontrado)")

os.unlink(tmp.name)
print("Upload concluído.")
PYEOF

    log_ok "HF Space atualizado."
fi

# ── 8. Commit git ────────────────────────────────────────────────────────────
log_info "Fazendo commit dos resultados..."
cd "$ROOT"
git add results/metrics/ results/figures/ results/rankings/ \
        data/processed/latent_2d.parquet \
        config/config.yaml src/jepa_spillover/viz/latent.py \
        2>/dev/null || true
git commit -m "feat: embeddings JEPA pós-treino + UMAP vs t-SNE + métricas atualizadas" \
    --allow-empty 2>/dev/null && log_ok "Commit realizado." || log_info "Nada novo para commitar."

log_ok "=== post_jepa.sh concluído com sucesso! ==="
echo ""
echo "Próximos passos sugeridos:"
echo "  1. Verificar métricas acima — se AUROC < 0.70, considerar mais dados/labels"
echo "  2. Verificar dashboard: https://huggingface.co/spaces/$HF_SPACE"
echo "  3. Expandir labels (Fase 2 do plano de melhorias)"
