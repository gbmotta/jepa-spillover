"""Pré-treino auto-supervisionado da JEPA genômica.

Lê o dataset curado, tokeniza as sequências, amostra blocos de contexto/alvo e treina
o modelo a prever embeddings-alvo no espaço latente. Salva checkpoint + embeddings.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch
from tqdm import tqdm

from ..config import Config, get_device, set_global_seed
from ..logger import get_logger
from ..models.jepa_genomic import GenomicJEPA, SequenceTokenizer
from ..security import safe_torch_load

log = get_logger(__name__)


def _sample_blocks(tokens, *, context_frac, n_targets, rng):
    """Divide a sequência tokenizada em um bloco de contexto e N blocos-alvo."""
    L = len(tokens)
    ctx_len = max(1, int(L * context_frac))
    start = rng.integers(0, max(1, L - ctx_len))
    context = tokens[start : start + ctx_len]
    context = np.pad(context, (0, L - len(context)))

    target_tokens, target_masks, target_pos = [], [], []
    block_len = max(1, L // (n_targets + 1))
    for m in range(n_targets):
        ts = rng.integers(0, max(1, L - block_len))
        block = np.zeros(L, dtype=np.int64)
        mask = np.zeros(L, dtype=np.int64)
        block[:block_len] = tokens[ts : ts + block_len]
        mask[:block_len] = (block[:block_len] != 0).astype(np.int64)
        target_tokens.append(block)
        target_masks.append(mask)
        target_pos.append(ts / max(1, L))
    return context, np.stack(target_tokens), np.stack(target_masks), np.array(target_pos, dtype=np.float32)


class JEPADataset(torch.utils.data.Dataset):
    def __init__(self, sequences, tokenizer, max_len, context_frac, n_targets, seed):
        self.seqs = sequences
        self.tok = tokenizer
        self.max_len = max_len
        self.context_frac = context_frac
        self.n_targets = n_targets
        self.rng = np.random.default_rng(seed)

    def __len__(self):
        return len(self.seqs)

    def __getitem__(self, idx):
        tokens = np.array(self.tok.encode(self.seqs[idx], self.max_len), dtype=np.int64)
        ctx, tt, tm, tp = _sample_blocks(
            tokens, context_frac=self.context_frac, n_targets=self.n_targets, rng=self.rng
        )
        return (
            torch.as_tensor(ctx, dtype=torch.long),
            torch.as_tensor(tt, dtype=torch.long),
            torch.as_tensor(tm, dtype=torch.long),
            torch.as_tensor(tp, dtype=torch.float32),
        )


def train(config_path: str | None = None) -> Path:
    cfg = Config.load(config_path)
    set_global_seed(cfg.get_path("project.seed", 42))
    device = get_device(cfg.get_path("project.device", "auto"))

    df = pd.read_parquet(cfg.resolve("data_processed") / "dataset.parquet")
    sequences = df["sequence"].tolist()

    k = int(cfg.get_path("features.kmer.k", 6))
    max_len = int(cfg.get_path("jepa.encoder.max_len", 256))
    tokenizer = SequenceTokenizer(k=k)

    ds = JEPADataset(
        sequences, tokenizer, max_len,
        context_frac=cfg.get_path("jepa.context_block_frac", 0.5),
        n_targets=int(cfg.get_path("jepa.num_target_blocks", 4)),
        seed=cfg.get_path("project.seed", 42),
    )
    dl = torch.utils.data.DataLoader(
        ds, batch_size=int(cfg.get_path("train.batch_size", 64)), shuffle=True,
        num_workers=int(cfg.get_path("train.num_workers", 0)),
    )

    model = GenomicJEPA(
        vocab_size=tokenizer.vocab_size,
        embed_dim=int(cfg.get_path("jepa.encoder.embed_dim", 256)),
        depth=int(cfg.get_path("jepa.encoder.depth", 6)),
        num_heads=int(cfg.get_path("jepa.encoder.num_heads", 8)),
        max_len=max_len,
        predictor_hidden=int(cfg.get_path("jepa.predictor.hidden_dim", 512)),
        predictor_depth=int(cfg.get_path("jepa.predictor.depth", 2)),
        ema_momentum=float(cfg.get_path("jepa.ema_momentum", 0.996)),
        dropout=float(cfg.get_path("jepa.encoder.dropout", 0.1)),
    ).to(device)

    epochs     = int(cfg.get_path("train.epochs", 50))
    save_every = int(cfg.get_path("train.save_every_epochs", 5))
    opt = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=float(cfg.get_path("train.lr", 3e-4)),
        weight_decay=float(cfg.get_path("train.weight_decay", 0.05)),
    )

    ckpt_dir = cfg.resolve("checkpoints")
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    ckpt     = ckpt_dir / "jepa_genomic.pt"
    ckpt_tmp = ckpt_dir / "jepa_genomic_latest.pt"

    # ── Retomar de checkpoint anterior se existir ──────────────────────────
    start_epoch = 0
    if ckpt_tmp.exists():
        saved = safe_torch_load(ckpt_tmp, map_location=device)
        if saved.get("epoch", 0) > 0:
            model.load_state_dict(saved["state_dict"])
            opt.load_state_dict(saved["optimizer"])
            start_epoch = saved["epoch"]
            log.info("Retomando de checkpoint: época %d/%d (loss=%.5f)",
                     start_epoch, epochs, saved.get("last_loss", float("nan")))
        else:
            log.info("Checkpoint encontrado mas sem época salva — iniciando do zero.")
    elif ckpt.exists():
        saved = safe_torch_load(ckpt, map_location=device)
        model.load_state_dict(saved["state_dict"])
        log.info("Pesos carregados de checkpoint final anterior — treinando do zero.")

    run = _maybe_trackio(cfg, epochs)
    log.info("Iniciando treino | device=%s | seqs=%d | epochs=%d | batch=%d | start=%d",
             device, len(sequences), epochs, dl.batch_size, start_epoch)
    model.train()
    epoch_bar = tqdm(range(start_epoch, epochs), desc="Epochs", unit="ep", ncols=90)
    for ep in epoch_bar:
        total = 0.0
        batch_bar = tqdm(dl, desc=f"Ep {ep+1}", unit="batch",
                         ncols=90, leave=False)
        for ctx, tt, tm, tp in batch_bar:
            ctx, tt, tm, tp = ctx.to(device), tt.to(device), tm.to(device), tp.to(device)
            opt.zero_grad()
            loss = model(ctx, tt, tm, tp)
            loss.backward()
            opt.step()
            model.update_target_encoder()
            total += loss.item()
            batch_bar.set_postfix(loss=f"{loss.item():.5f}")
        avg = total / max(1, len(dl))
        epoch_bar.set_postfix(avg_loss=f"{avg:.5f}")
        log.info("Epoch %d/%d — loss=%.5f", ep + 1, epochs, avg)
        if run is not None:
            run.log({"epoch": ep + 1, "jepa_loss": avg})

        # Salvar checkpoint intermediário a cada N épocas
        if (ep + 1) % save_every == 0 or (ep + 1) == epochs:
            torch.save({
                "state_dict": model.state_dict(),
                "optimizer":  opt.state_dict(),
                "epoch":      ep + 1,
                "last_loss":  avg,
                "k": k, "max_len": max_len,
                "vocab_size": tokenizer.vocab_size,
            }, ckpt_tmp)
            log.info("Checkpoint intermediário salvo: época %d/%d (loss=%.5f)", ep + 1, epochs, avg)

    torch.save({"state_dict": model.state_dict(), "k": k, "max_len": max_len,
                "vocab_size": tokenizer.vocab_size}, ckpt)
    log.info("Checkpoint final salvo: %s", ckpt)

    _export_embeddings(cfg, model, tokenizer, df, max_len, device)
    return ckpt


@torch.no_grad()
def _export_embeddings(cfg, model, tokenizer, df, max_len, device):
    model.eval()
    log.info("Exportando embeddings JEPA para %d sequências...", len(df))
    embs = []
    for seq in tqdm(df["sequence"], desc="Embeddings", unit="seq", ncols=90):
        tokens = torch.as_tensor([tokenizer.encode(seq, max_len)], dtype=torch.long, device=device)
        embs.append(model.encode(tokens).squeeze(0).cpu().numpy())
    emb = np.vstack(embs).astype(np.float32)
    out = cfg.resolve("data_processed") / "jepa_embeddings.npz"
    np.savez_compressed(out, embeddings=emb, accession=df["accession"].astype(str).to_numpy())
    log.info("Embeddings JEPA salvos: %s — shape %s", out, emb.shape)


def _maybe_trackio(cfg, epochs):
    try:
        import trackio
        run = trackio.init(
            project=cfg.get_path("project.name", "jepa-spillover"),
            config={"epochs": epochs, "lr": cfg.get_path("train.lr", 3e-4)},
        )
        log.info("Trackio inicializado")
        return run
    except Exception as exc:
        log.debug("Trackio não disponível: %s", exc)
        return None
