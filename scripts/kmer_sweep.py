"""Benchmark de diferentes valores de k para k-mers genômicos.

Compara k ∈ {3, 4, 5, 6} em:
  - Variância explicada pelo PCA (128 componentes)
  - AUROC no fine-tuning (Regressão Logística 5-fold CV)
  - Tempo de computação
  - Uso de RAM

Uso:
    python scripts/kmer_sweep.py
    python scripts/kmer_sweep.py --k 3 4 5 6 7 --dim 128 --max-seqs 3000
    python scripts/kmer_sweep.py --output results/kmer_sweep
"""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from tqdm import tqdm

# ── setup path ────────────────────────────────────────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jepa_spillover.data.kmers import kmer_matrix_chunks
from jepa_spillover.logger import get_logger

log = get_logger("scripts.kmer_sweep")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def load_dataset(data_processed: Path, max_seqs: int | None) -> pd.DataFrame:
    parquet = data_processed / "dataset.parquet"
    if not parquet.exists():
        log.error("dataset.parquet não encontrado em %s", data_processed)
        sys.exit(1)
    # Ler colunas disponíveis (spillover_label pode não existir ainda)
    import pyarrow.parquet as pq
    available = pq.read_schema(parquet).names
    cols = ["accession", "sequence", "family"] + (["spillover_label"] if "spillover_label" in available else [])
    df = pd.read_parquet(parquet, columns=cols)
    if max_seqs and len(df) > max_seqs:
        log.info("Subsampling %d → %d sequências", len(df), max_seqs)
        df = df.sample(max_seqs, random_state=42).reset_index(drop=True)
    log.info("Dataset: %d sequências, %d famílias", len(df), df["family"].nunique())
    return df


def run_single_k(
    sequences: list[str],
    labels: np.ndarray,
    k: int,
    dim: int,
    chunk_size: int,
) -> dict:
    """Treina e avalia uma configuração k."""
    from sklearn.decomposition import IncrementalPCA
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.preprocessing import label_binarize
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    vocab_size = 4 ** k
    n = len(sequences)
    n_comp = min(dim, n - 1, vocab_size)
    safe_chunk = max(chunk_size, n_comp + 1)

    log.info("── k=%d | vocab=%d | n_comp=%d ──", k, vocab_size, n_comp)

    # ── Medir RAM e tempo ──────────────────────────────────────────────────
    tracemalloc.start()
    t0 = time.perf_counter()

    # Fase 1: fit PCA
    ipca = IncrementalPCA(n_components=n_comp)
    for chunk in kmer_matrix_chunks(
        sequences, k=k, chunk_size=safe_chunk, show_progress=True
    ):
        ipca.partial_fit(chunk)
    var_explained = float(ipca.explained_variance_ratio_.sum())

    # Fase 2: transform
    parts = []
    for chunk in kmer_matrix_chunks(
        sequences, k=k, chunk_size=safe_chunk, show_progress=False
    ):
        parts.append(ipca.transform(chunk).astype(np.float32))
    emb = np.vstack(parts)
    del parts

    elapsed = time.perf_counter() - t0
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    log.info(
        "k=%d → %.1f%% var | %.1fs | %.0f MB RAM",
        k, var_explained * 100, elapsed, peak_bytes / 1e6,
    )

    # ── Downstream: Regressão Logística (5-fold CV) ────────────────────────
    # Classificação binária: spillover_label (se existir) ou multi-família
    n_classes = len(np.unique(labels))
    if n_classes < 2:
        log.warning("Apenas 1 classe — pulando avaliação downstream")
        auroc = float("nan")
    else:
        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, random_state=42, n_jobs=-1)),
        ])
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        scoring = "roc_auc" if n_classes == 2 else "roc_auc_ovr_weighted"
        scores = cross_val_score(pipe, emb, labels, cv=cv, scoring=scoring, n_jobs=1)
        auroc = float(scores.mean())
        log.info("k=%d → AUROC 5-fold = %.4f ± %.4f", k, auroc, scores.std())

    return {
        "k": k,
        "vocab_size": vocab_size,
        "n_components": n_comp,
        "var_explained": round(var_explained, 4),
        "auroc": round(auroc, 4),
        "time_s": round(elapsed, 2),
        "peak_ram_mb": round(peak_bytes / 1e6, 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Visualizações
# ══════════════════════════════════════════════════════════════════════════════

def plot_results(results: list[dict], out_dir: Path) -> None:
    df = pd.DataFrame(results)
    ks = df["k"].tolist()

    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle("Benchmark de k-mers — JEPA Spillover", fontsize=14, fontweight="bold")

    palette = plt.cm.tab10.colors

    # 1. Variância explicada
    ax = axes[0, 0]
    bars = ax.bar(ks, df["var_explained"] * 100, color=palette[:len(ks)])
    ax.set_xlabel("k")
    ax.set_ylabel("Variância explicada (%)")
    ax.set_title("PCA — Variância explicada (128 componentes)")
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())
    ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=10)
    ax.set_xticks(ks)

    # 2. AUROC downstream
    ax = axes[0, 1]
    valid = df.dropna(subset=["auroc"])
    bars = ax.bar(valid["k"], valid["auroc"], color=palette[:len(valid)])
    ax.set_xlabel("k")
    ax.set_ylabel("AUROC")
    ax.set_title("Regressão Logística 5-fold CV")
    ax.set_ylim(0.4, 1.05)
    ax.axhline(0.5, color="gray", linestyle="--", linewidth=0.8, label="Chance")
    ax.legend(fontsize=9)
    ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=10)
    ax.set_xticks(valid["k"].tolist())

    # 3. Tempo
    ax = axes[1, 0]
    ax.plot(ks, df["time_s"], "o-", color=palette[2], linewidth=2, markersize=8)
    ax.set_xlabel("k")
    ax.set_ylabel("Tempo (s)")
    ax.set_title("Tempo total de computação")
    for x, y in zip(ks, df["time_s"]):
        ax.annotate(f"{y:.1f}s", (x, y), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=9)
    ax.set_xticks(ks)

    # 4. RAM
    ax = axes[1, 1]
    ax.plot(ks, df["peak_ram_mb"], "s-", color=palette[3], linewidth=2, markersize=8)
    ax.set_xlabel("k")
    ax.set_ylabel("RAM pico (MB)")
    ax.set_title("Consumo máximo de RAM")
    for x, y in zip(ks, df["peak_ram_mb"]):
        ax.annotate(f"{y:.0f} MB", (x, y), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=9)
    ax.set_xticks(ks)

    plt.tight_layout()
    fig_path = out_dir / "kmer_sweep.png"
    fig.savefig(fig_path, dpi=150, bbox_inches="tight")
    log.info("Figura salva: %s", fig_path)
    plt.close(fig)

    # Tabela resumo
    print("\n" + "═" * 72)
    print(f"{'k':>4} | {'vocab':>6} | {'var%':>6} | {'AUROC':>7} | {'tempo':>7} | {'RAM MB':>8}")
    print("─" * 72)
    for r in results:
        auroc_str = f"{r['auroc']:.4f}" if not np.isnan(r["auroc"]) else "  —   "
        print(
            f"{r['k']:>4} | {r['vocab_size']:>6,} | "
            f"{r['var_explained']*100:>5.1f}% | {auroc_str:>7} | "
            f"{r['time_s']:>6.1f}s | {r['peak_ram_mb']:>7.0f}"
        )
    print("═" * 72 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark k-mers")
    parser.add_argument("--k", nargs="+", type=int, default=[3, 4, 5, 6],
                        help="Valores de k a testar (default: 3 4 5 6)")
    parser.add_argument("--dim", type=int, default=128,
                        help="Dimensão do PCA (default: 128)")
    parser.add_argument("--chunk-size", type=int, default=500,
                        help="Chunk para IncrementalPCA (default: 500)")
    parser.add_argument("--max-seqs", type=int, default=None,
                        help="Subsample máximo de sequências (default: todas)")
    parser.add_argument("--output", type=str, default="results/kmer_sweep",
                        help="Diretório de saída (default: results/kmer_sweep)")
    parser.add_argument("--config", type=str, default=None,
                        help="Caminho para config.yaml (default: auto)")
    args = parser.parse_args()

    # Carregar configuração
    from jepa_spillover.config import Config
    cfg = Config.load(args.config)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_dataset(cfg.resolve("data_processed"), args.max_seqs)
    sequences = df["sequence"].tolist()

    # Labels para avaliação downstream
    if "spillover_label" in df.columns and df["spillover_label"].notna().any():
        labels = df["spillover_label"].fillna(0).astype(int).to_numpy()
        log.info("Target: spillover_label (binário)")
    else:
        # Fallback: família como label multi-classe
        labels = pd.Categorical(df["family"]).codes
        log.info("Target: família viral (multi-classe, %d classes)", len(np.unique(labels)))

    results = []
    for k in sorted(args.k):
        log.info("\n" + "═" * 60)
        log.info("Testando k = %d  (vocab = %d features)", k, 4**k)
        log.info("═" * 60)
        try:
            res = run_single_k(sequences, labels, k=k, dim=args.dim, chunk_size=args.chunk_size)
            results.append(res)
        except MemoryError:
            log.error("k=%d: MemoryError — pulando", k)
            results.append({
                "k": k, "vocab_size": 4**k, "n_components": min(args.dim, 4**k),
                "var_explained": float("nan"), "auroc": float("nan"),
                "time_s": float("nan"), "peak_ram_mb": float("nan"),
            })

    # Salvar resultados JSON
    json_path = out_dir / "kmer_sweep_results.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log.info("Resultados JSON: %s", json_path)

    # Plotar
    plot_results(results, out_dir)

    # Recomendação automática
    valid = [r for r in results if not np.isnan(r["auroc"])]
    if valid:
        best_auroc = max(valid, key=lambda r: r["auroc"])
        best_var   = max(valid, key=lambda r: r["var_explained"])
        print(f"✓ Melhor AUROC:              k={best_auroc['k']} ({best_auroc['auroc']:.4f})")
        print(f"✓ Maior variância explicada: k={best_var['k']} ({best_var['var_explained']*100:.1f}%)")
        # Trade-off: penalizar k alto pelo tempo
        scores = {
            r["k"]: 0.6 * r["auroc"] + 0.2 * r["var_explained"] - 0.2 * (r["time_s"] / max(r2["time_s"] for r2 in valid))
            for r in valid
        }
        best_tradeoff = max(scores, key=scores.get)
        print(f"✓ Melhor trade-off (AUROC × var × tempo): k={best_tradeoff}\n")


if __name__ == "__main__":
    main()
