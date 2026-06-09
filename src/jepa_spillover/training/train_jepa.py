"""Pré-treino auto-supervisionado da JEPA genômica.

Lê o dataset curado, tokeniza as sequências, amostra blocos de contexto/alvo e treina
o modelo a prever embeddings-alvo no espaço latente. Salva checkpoint + embeddings.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch

from ..config import Config, get_device, set_global_seed
from ..models.jepa_genomic import GenomicJEPA, SequenceTokenizer


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

    epochs = int(cfg.get_path("train.epochs", 50))
    opt = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=float(cfg.get_path("train.lr", 3e-4)),
        weight_decay=float(cfg.get_path("train.weight_decay", 0.05)),
    )

    run = _maybe_trackio(cfg, epochs)
    print(f"[train] device={device} | seqs={len(sequences)} | epochs={epochs}")
    model.train()
    for ep in range(epochs):
        total = 0.0
        for ctx, tt, tm, tp in dl:
            ctx, tt, tm, tp = ctx.to(device), tt.to(device), tm.to(device), tp.to(device)
            opt.zero_grad()
            loss = model(ctx, tt, tm, tp)
            loss.backward()
            opt.step()
            model.update_target_encoder()
            total += loss.item()
        avg = total / max(1, len(dl))
        print(f"  epoch {ep + 1}/{epochs}  loss={avg:.5f}")
        if run is not None:
            run.log({"epoch": ep + 1, "jepa_loss": avg})

    ckpt_dir = cfg.resolve("checkpoints")
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    ckpt = ckpt_dir / "jepa_genomic.pt"
    torch.save({"state_dict": model.state_dict(), "k": k, "max_len": max_len,
                "vocab_size": tokenizer.vocab_size}, ckpt)
    print(f"[train] Checkpoint salvo em {ckpt}")

    _export_embeddings(cfg, model, tokenizer, df, max_len, device)
    return ckpt


@torch.no_grad()
def _export_embeddings(cfg, model, tokenizer, df, max_len, device):
    model.eval()
    embs = []
    for seq in df["sequence"]:
        tokens = torch.as_tensor([tokenizer.encode(seq, max_len)], dtype=torch.long, device=device)
        embs.append(model.encode(tokens).squeeze(0).cpu().numpy())
    emb = np.vstack(embs).astype(np.float32)
    out = cfg.resolve("data_processed") / "jepa_embeddings.npz"
    np.savez_compressed(out, embeddings=emb, accession=df["accession"].to_numpy())
    print(f"[train] Embeddings JEPA salvos em {out} — shape {emb.shape}")


def _maybe_trackio(cfg, epochs):
    try:
        import trackio

        return trackio.init(
            project=cfg.get_path("project.name", "jepa-spillover"),
            config={"epochs": epochs, "lr": cfg.get_path("train.lr", 3e-4)},
        )
    except Exception:
        return None
