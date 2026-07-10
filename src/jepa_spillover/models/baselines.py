"""Modelos de referência (baselines) para comparação com a JEPA.

- ``kmer_logreg`` / ``kmer_rf``: classificadores clássicos sobre frequências de k-mers.
- ``LSTMClassifier`` / ``TransformerClassifier``: redes supervisionadas sobre a sequência
  tokenizada (treinadas do zero com rótulos).
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from tqdm import tqdm

from ..logger import get_logger

log = get_logger(__name__)


def build_sklearn_baseline(kind: str = "logreg", seed: int = 42):
    """Cria um classificador scikit-learn para usar sobre k-mers/embeddings."""
    if kind == "logreg":
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)
    if kind == "rf":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(n_estimators=400, class_weight="balanced", random_state=seed, n_jobs=-1)
    raise ValueError(f"baseline desconhecido: {kind}")


class LSTMClassifier(nn.Module):
    def __init__(self, vocab_size: int, embed_dim: int = 128, hidden: int = 128, n_classes: int = 2):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.lstm = nn.LSTM(embed_dim, hidden, batch_first=True, bidirectional=True)
        self.head = nn.Linear(hidden * 2, n_classes)

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        x = self.emb(tokens)
        _, (h, _) = self.lstm(x)
        h = torch.cat([h[-2], h[-1]], dim=-1)
        return self.head(h)


class TransformerClassifier(nn.Module):
    def __init__(self, vocab_size: int, embed_dim: int = 128, depth: int = 4,
                 num_heads: int = 4, max_len: int = 512, n_classes: int = 2):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.pos = nn.Parameter(torch.zeros(1, max_len, embed_dim))
        layer = nn.TransformerEncoderLayer(embed_dim, num_heads, embed_dim * 4,
                                           batch_first=True, activation="gelu")
        self.encoder = nn.TransformerEncoder(layer, depth)
        self.head = nn.Linear(embed_dim, n_classes)
        nn.init.trunc_normal_(self.pos, std=0.02)

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        x = self.emb(tokens) + self.pos[:, : tokens.size(1)]
        x = self.encoder(x, src_key_padding_mask=(tokens == 0))
        return self.head(x.mean(dim=1))


def train_torch_classifier(model, X, y, *, epochs=10, lr=1e-3, batch_size=32, device="cpu"):
    """Loop de treino genérico para os baselines em PyTorch."""
    model = model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    crit = nn.CrossEntropyLoss()
    X_t = torch.as_tensor(np.asarray(X), dtype=torch.long)
    y_t = torch.as_tensor(np.asarray(y), dtype=torch.long)
    ds = torch.utils.data.TensorDataset(X_t, y_t)
    dl = torch.utils.data.DataLoader(ds, batch_size=batch_size, shuffle=True)
    log.info("Baseline torch: epochs=%d batch=%d device=%s n=%d", epochs, batch_size, device, len(ds))
    model.train()
    epoch_bar = tqdm(range(epochs), desc="Baseline epochs", unit="ep", ncols=90)
    for ep in epoch_bar:
        total = 0.0
        for xb, yb in dl:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
            total += loss.item()
        avg = total / max(1, len(dl))
        epoch_bar.set_postfix(loss=f"{avg:.4f}")
        log.debug("baseline epoch %d/%d loss=%.4f", ep + 1, epochs, avg)
    log.info("Baseline treinado — última loss=%.4f", avg)
    return model
