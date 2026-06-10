"""Interface de linha de comando do JEPA-Spillover.

Exemplos:
    python -m jepa_spillover.cli synth         # gera dados sintéticos de demonstração
    python -m jepa_spillover.cli curate
    python -m jepa_spillover.cli features
    python -m jepa_spillover.cli train
    python -m jepa_spillover.cli finetune
    python -m jepa_spillover.cli evaluate
    python -m jepa_spillover.cli all           # pipeline completo (com dados sintéticos)
"""

from __future__ import annotations

import argparse
import os
import time


def _add_config(p):
    p.add_argument("--config", default=None, help="Caminho do config.yaml")
    p.add_argument("--debug", action="store_true", help="Ativa log DEBUG")
    return p


def _apply_debug(args) -> None:
    if getattr(args, "debug", False):
        os.environ["JEPA_LOG_LEVEL"] = "DEBUG"


def cmd_synth(args):
    _apply_debug(args)
    from .config import Config
    from .data.synthetic import generate
    from .logger import get_logger

    log = get_logger("cli.synth")
    cfg = Config.load(args.config)
    out = cfg.resolve("data_processed")
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    df = generate(n_per_family=args.n, seed=cfg.get_path("project.seed", 42))
    df.to_parquet(out / "dataset.parquet")
    log.info("Dataset sintético: %d sequências → %s (%.1fs)", len(df), out / "dataset.parquet", time.time() - t0)


def cmd_curate(args):
    _apply_debug(args)
    from .data.curate import curate
    curate(args.config)


def cmd_features(args):
    _apply_debug(args)
    from .features.embeddings import build_embeddings
    build_embeddings(args.config)


def cmd_train(args):
    _apply_debug(args)
    from .training.train_jepa import train
    train(args.config)


def cmd_finetune(args):
    _apply_debug(args)
    from .training.finetune import finetune
    finetune(args.config)


def cmd_evaluate(args):
    _apply_debug(args)
    from .evaluation.ranking import build_ranking
    from .logger import get_logger
    from .viz.latent import make_figures

    log = get_logger("cli.evaluate")
    t0 = time.time()
    make_figures(args.config)
    build_ranking(args.config)
    log.info("Avaliação concluída em %.1fs", time.time() - t0)


def cmd_all(args):
    _apply_debug(args)
    from .logger import get_logger

    log = get_logger("cli.all")
    t0 = time.time()

    log.info("=== Pipeline completo iniciado ===")
    cmd_synth(args)
    cmd_curate(args)
    cmd_features(args)
    if not args.skip_train:
        cmd_train(args)
    else:
        log.info("Pré-treino JEPA pulado (--skip-train)")
    cmd_finetune(args)
    cmd_evaluate(args)
    log.info("=== Pipeline completo concluído em %.1fs ===", time.time() - t0)
    log.info("Resultados em results/  |  rode 'make dashboard' para visualizar")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jepa-spillover", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = _add_config(sub.add_parser("synth", help="Gera dataset sintético"))
    p.add_argument("--n", type=int, default=120, help="Sequências por família")
    p.set_defaults(func=cmd_synth)

    _add_config(sub.add_parser("curate", help="Curadoria")).set_defaults(func=cmd_curate)
    _add_config(sub.add_parser("features", help="k-mers + embeddings")).set_defaults(func=cmd_features)
    _add_config(sub.add_parser("train", help="Pré-treino JEPA")).set_defaults(func=cmd_train)
    _add_config(sub.add_parser("finetune", help="Fine-tuning supervisionado")).set_defaults(func=cmd_finetune)
    _add_config(sub.add_parser("evaluate", help="UMAP/t-SNE + ranking")).set_defaults(func=cmd_evaluate)

    p = _add_config(sub.add_parser("all", help="Pipeline completo (demo sintética)"))
    p.add_argument("--n", type=int, default=120)
    p.add_argument("--skip-train", action="store_true", help="Pula pré-treino JEPA (usa k-mer/PCA)")
    p.set_defaults(func=cmd_all)

    return parser


def app() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    app()
