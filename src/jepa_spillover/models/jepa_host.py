"""Extensão vírus-hospedeiro da JEPA.

Recebe o embedding viral (da JEPA genômica) como contexto e prevê o embedding do
hospedeiro associado, aprendendo compatibilidades latentes vírus-hospedeiro.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class HostEncoder(nn.Module):
    """Codifica atributos do hospedeiro (taxonomia/filogenia/ecologia) em embedding."""

    def __init__(self, n_host_features: int, embed_dim: int = 256, hidden: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_host_features, hidden), nn.GELU(),
            nn.Linear(hidden, embed_dim), nn.LayerNorm(embed_dim),
        )

    def forward(self, host_features: torch.Tensor) -> torch.Tensor:
        return self.net(host_features)


class VirusHostJEPA(nn.Module):
    """Prevê o embedding do hospedeiro a partir do embedding viral."""

    def __init__(self, virus_dim: int = 256, host_feat_dim: int = 32,
                 embed_dim: int = 256, hidden: int = 512):
        super().__init__()
        self.host_encoder = HostEncoder(host_feat_dim, embed_dim, hidden)
        self.predictor = nn.Sequential(
            nn.Linear(virus_dim, hidden), nn.GELU(),
            nn.Linear(hidden, embed_dim),
        )

    def forward(self, virus_emb: torch.Tensor, host_features: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            host_emb = self.host_encoder(host_features)
        pred = self.predictor(virus_emb)
        return nn.functional.smooth_l1_loss(pred, host_emb)

    @torch.no_grad()
    def compatibility(self, virus_emb: torch.Tensor, host_features: torch.Tensor) -> torch.Tensor:
        """Score de compatibilidade latente (cosseno) entre vírus e hospedeiro."""
        pred = self.predictor(virus_emb)
        host_emb = self.host_encoder(host_features)
        return torch.cosine_similarity(pred, host_emb, dim=-1)
