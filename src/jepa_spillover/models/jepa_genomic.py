"""JEPA genômica: codificador de contexto, codificador-alvo (EMA) e preditor latente.

Implementação em PyTorch, estilo I-JEPA adaptado a sequências genômicas tokenizadas
por k-mers. O objetivo é prever, no espaço latente, o embedding de blocos-alvo a partir
de um bloco de contexto.
"""

from __future__ import annotations

import copy

import torch
import torch.nn as nn


class SequenceTokenizer:
    """Tokeniza sequências em k-mers sobrepostos -> índices inteiros."""

    def __init__(self, k: int = 6, alphabet: str = "ACGT"):
        self.k = k
        from itertools import product

        self.vocab = {"".join(p): i + 1 for i, p in enumerate(product(alphabet, repeat=k))}
        self.pad_id = 0
        self.vocab_size = len(self.vocab) + 1

    def encode(self, seq: str, max_tokens: int) -> list[int]:
        seq = seq.upper().replace("U", "T")
        ids = [self.vocab.get(seq[i : i + self.k], self.pad_id) for i in range(len(seq) - self.k + 1)]
        ids = ids[:max_tokens]
        if len(ids) < max_tokens:
            ids += [self.pad_id] * (max_tokens - len(ids))
        return ids


class TransformerEncoder(nn.Module):
    """Codificador Transformer com embedding de tokens e posições."""

    def __init__(self, vocab_size: int, embed_dim: int, depth: int, num_heads: int,
                 max_len: int, dropout: float = 0.1):
        super().__init__()
        self.token_emb = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.pos_emb = nn.Parameter(torch.zeros(1, max_len, embed_dim))
        layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=num_heads, dim_feedforward=embed_dim * 4,
            dropout=dropout, batch_first=True, activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=depth)
        self.norm = nn.LayerNorm(embed_dim)
        nn.init.trunc_normal_(self.pos_emb, std=0.02)

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        x = self.token_emb(tokens) + self.pos_emb[:, : tokens.size(1)]
        pad_mask = tokens == 0
        x = self.encoder(x, src_key_padding_mask=pad_mask)
        return self.norm(x)


class Predictor(nn.Module):
    """Prevê o embedding-alvo a partir do embedding de contexto + posição-alvo."""

    def __init__(self, embed_dim: int, hidden_dim: int, depth: int = 2):
        super().__init__()
        layers, d = [], embed_dim * 2
        for _ in range(depth):
            layers += [nn.Linear(d, hidden_dim), nn.GELU()]
            d = hidden_dim
        layers.append(nn.Linear(d, embed_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, context_vec: torch.Tensor, target_pos: torch.Tensor) -> torch.Tensor:
        return self.net(torch.cat([context_vec, target_pos], dim=-1))


class GenomicJEPA(nn.Module):
    """Modelo JEPA genômico completo."""

    def __init__(self, *, vocab_size: int, embed_dim: int = 256, depth: int = 6,
                 num_heads: int = 8, max_len: int = 512, predictor_hidden: int = 512,
                 predictor_depth: int = 2, ema_momentum: float = 0.996, dropout: float = 0.1):
        super().__init__()
        self.context_encoder = TransformerEncoder(vocab_size, embed_dim, depth, num_heads, max_len, dropout)
        self.target_encoder = copy.deepcopy(self.context_encoder)
        for p in self.target_encoder.parameters():
            p.requires_grad = False
        self.predictor = Predictor(embed_dim, predictor_hidden, predictor_depth)
        self.pos_proj = nn.Linear(1, embed_dim)
        self.ema_momentum = ema_momentum
        self.embed_dim = embed_dim

    @torch.no_grad()
    def update_target_encoder(self) -> None:
        m = self.ema_momentum
        for pc, pt in zip(self.context_encoder.parameters(), self.target_encoder.parameters()):
            pt.data.mul_(m).add_(pc.data, alpha=1.0 - m)

    @staticmethod
    def _masked_mean(x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        w = mask.unsqueeze(-1).float()
        return (x * w).sum(dim=1) / w.sum(dim=1).clamp(min=1.0)

    def forward(self, context_tokens, target_tokens, target_masks, target_positions):
        """Calcula a perda JEPA (L2 latente) para um batch.

        context_tokens: (B, L)
        target_tokens:  (B, M, L)  M blocos-alvo
        target_masks:   (B, M, L)  máscara dos tokens válidos de cada bloco-alvo
        target_positions: (B, M)   posição relativa (0-1) de cada bloco-alvo
        """
        ctx = self.context_encoder(context_tokens)               # (B, L, D)
        ctx_vec = ctx.mean(dim=1)                                 # (B, D)

        with torch.no_grad():
            B, M, L = target_tokens.shape
            tgt = self.target_encoder(target_tokens.view(B * M, L)).view(B, M, L, -1)
            tgt_vec = self._masked_mean(tgt.view(B * M, L, -1), target_masks.view(B * M, L)).view(B, M, -1)

        pos_emb = self.pos_proj(target_positions.unsqueeze(-1))    # (B, M, D)
        ctx_rep = ctx_vec.unsqueeze(1).expand(-1, target_tokens.size(1), -1)
        pred = self.predictor(ctx_rep, pos_emb)                    # (B, M, D)

        loss = nn.functional.smooth_l1_loss(pred, tgt_vec)
        return loss

    @torch.no_grad()
    def encode(self, tokens: torch.Tensor) -> torch.Tensor:
        """Embedding de uma sequência (média dos tokens do codificador de contexto)."""
        return self.context_encoder(tokens).mean(dim=1)
