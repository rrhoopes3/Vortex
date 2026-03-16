"""Attention Residuals (AttnRes) — Drop-in replacement for standard residual connections.

Implements the method from:
    "Attention Residuals" (Chen et al., 2026)
    https://github.com/MoonshotAI/Attention-Residuals

Standard residual connections accumulate layer outputs with fixed unit weights:
    h_l = h_{l-1} + f_l(h_{l-1})

This causes hidden-state magnitudes to grow unboundedly with depth (PreNorm dilution).

AttnRes replaces fixed accumulation with softmax attention over preceding outputs:
    h_l = sum_{i=0}^{l-1} alpha_{i->l} * v_i

where alpha weights are computed via a single learned pseudo-query per layer,
giving each layer selective, content-aware access to all earlier representations.

Two variants:
    - FullAttnRes: O(Ld) memory, attends over all previous layer outputs
    - BlockAttnRes: O(Nd) memory, partitions layers into N blocks (~8),
      standard residuals within blocks, attention across block boundaries
"""

from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization."""

    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: Tensor) -> Tensor:
        rms = torch.rsqrt(x.float().pow(2).mean(-1, keepdim=True) + self.eps)
        return (x.float() * rms).to(x.dtype) * self.weight


class AttnResProjection(nn.Module):
    """Learned pseudo-query projection for depth-wise attention.

    Single linear projection w ∈ R^d that computes attention logits
    over previous layer representations.
    """

    def __init__(self, dim: int):
        super().__init__()
        self.proj = nn.Linear(dim, 1, bias=False)
        nn.init.normal_(self.proj.weight, std=0.02)

    def forward(self, keys: Tensor) -> Tensor:
        """Compute attention logits.

        Args:
            keys: [N, B, T, D] normalized representations

        Returns:
            logits: [N, B, T] unnormalized attention scores
        """
        return self.proj(keys).squeeze(-1)


def attn_res_aggregate(
    values: list[Tensor],
    proj: AttnResProjection,
    norm: RMSNorm,
) -> Tensor:
    """Compute attention-weighted aggregation over depth.

    Args:
        values: List of N tensors, each [B, T, D] — previous layer outputs.
        proj: Learned pseudo-query projection.
        norm: RMSNorm for key computation.

    Returns:
        h: [B, T, D] — attention-weighted sum of values.
    """
    V = torch.stack(values, dim=0)  # [N, B, T, D]
    K = norm(V)
    logits = proj(K)  # [N, B, T]
    weights = logits.softmax(dim=0)  # [N, B, T]
    h = torch.einsum("n b t, n b t d -> b t d", weights, V)
    return h


class FullAttnResLayer(nn.Module):
    """A single transformer layer with Full Attention Residuals.

    Replaces both the pre-attention and pre-MLP residual connections
    with depth-wise attention over ALL previous layer outputs.

    Memory: O(Ld) where L = number of layers, d = hidden dim.
    """

    def __init__(
        self,
        dim: int,
        attn: nn.Module,
        mlp: nn.Module,
        attn_norm: Optional[nn.Module] = None,
        mlp_norm: Optional[nn.Module] = None,
    ):
        super().__init__()
        self.attn = attn
        self.mlp = mlp
        self.attn_norm = attn_norm or RMSNorm(dim)
        self.mlp_norm = mlp_norm or RMSNorm(dim)

        # AttnRes projections — one for pre-attention, one for pre-MLP
        self.attn_res_proj = AttnResProjection(dim)
        self.attn_res_norm = RMSNorm(dim)
        self.mlp_res_proj = AttnResProjection(dim)
        self.mlp_res_norm = RMSNorm(dim)

    def forward(
        self,
        hidden_states: Tensor,
        layer_history: list[Tensor],
        **attn_kwargs,
    ) -> tuple[Tensor, list[Tensor]]:
        """Forward pass with full attention residuals.

        Args:
            hidden_states: [B, T, D] current hidden states.
            layer_history: List of previous layer outputs (starts with embedding).
            **attn_kwargs: Passed to the attention module (mask, position_ids, etc.).

        Returns:
            output: [B, T, D] layer output.
            layer_history: Updated history including this layer's output.
        """
        # Pre-attention: attend over all previous outputs
        all_prev = layer_history + [hidden_states]
        h = attn_res_aggregate(all_prev, self.attn_res_proj, self.attn_res_norm)

        # Self-attention
        attn_out = self.attn(self.attn_norm(h), **attn_kwargs)
        post_attn = hidden_states + attn_out

        # Pre-MLP: attend over all previous outputs + post-attn
        all_prev_mlp = layer_history + [post_attn]
        h = attn_res_aggregate(all_prev_mlp, self.mlp_res_proj, self.mlp_res_norm)

        # MLP
        mlp_out = self.mlp(self.mlp_norm(h))
        output = post_attn + mlp_out

        # Record this layer's output
        layer_history = layer_history + [output]
        return output, layer_history


class BlockAttnResLayer(nn.Module):
    """A single transformer layer with Block Attention Residuals.

    Partitions layers into blocks. Within blocks, standard residuals accumulate.
    Attention operates only over block-level representations + the current
    intra-block partial sum.

    Memory: O(Nd) where N = number of blocks (typically ~8).

    This is the practical variant recommended by the paper — it recovers most
    of Full AttnRes's gains with marginal overhead.
    """

    def __init__(
        self,
        dim: int,
        attn: nn.Module,
        mlp: nn.Module,
        layer_number: int,
        block_size: int = 8,
        attn_norm: Optional[nn.Module] = None,
        mlp_norm: Optional[nn.Module] = None,
    ):
        super().__init__()
        self.attn = attn
        self.mlp = mlp
        self.layer_number = layer_number
        self.block_size = block_size
        self.attn_norm = attn_norm or RMSNorm(dim)
        self.mlp_norm = mlp_norm or RMSNorm(dim)

        # AttnRes projections
        self.attn_res_proj = AttnResProjection(dim)
        self.attn_res_norm = RMSNorm(dim)
        self.mlp_res_proj = AttnResProjection(dim)
        self.mlp_res_norm = RMSNorm(dim)

    def forward(
        self,
        hidden_states: Tensor,
        blocks: list[Tensor],
        partial_block: Optional[Tensor] = None,
        **attn_kwargs,
    ) -> tuple[Tensor, list[Tensor], Tensor]:
        """Forward pass with block attention residuals.

        Args:
            hidden_states: [B, T, D] current hidden states.
            blocks: List of completed block representations.
            partial_block: [B, T, D] intra-block partial sum, or None at block start.
            **attn_kwargs: Passed to the attention module.

        Returns:
            output: [B, T, D] layer output.
            blocks: Updated block list (new block appended at boundaries).
            partial_block: Updated intra-block partial sum.
        """
        if partial_block is None:
            partial_block = hidden_states

        # Pre-attention: attend over blocks + partial sum
        h = _block_attn_res(
            blocks, partial_block, self.attn_res_proj, self.attn_res_norm
        )

        # Check block boundary (block_size counts attn + mlp; each layer has 2)
        layers_per_block = self.block_size // 2
        if layers_per_block > 0 and self.layer_number % layers_per_block == 0:
            blocks = blocks + [partial_block]
            partial_block = torch.zeros_like(hidden_states)

        # Self-attention
        attn_out = self.attn(self.attn_norm(h), **attn_kwargs)
        partial_block = partial_block + attn_out

        # Pre-MLP: attend over blocks + updated partial sum
        h = _block_attn_res(
            blocks, partial_block, self.mlp_res_proj, self.mlp_res_norm
        )

        # MLP
        mlp_out = self.mlp(self.mlp_norm(h))
        partial_block = partial_block + mlp_out

        return partial_block, blocks, partial_block


def _block_attn_res(
    blocks: list[Tensor],
    partial_block: Tensor,
    proj: AttnResProjection,
    norm: RMSNorm,
) -> Tensor:
    """Inter-block attention: attend over block reps + partial sum.

    Args:
        blocks: N tensors of shape [B, T, D] — completed block representations.
        partial_block: [B, T, D] — intra-block partial sum.
        proj: Learned pseudo-query projection.
        norm: RMSNorm for key computation.

    Returns:
        h: [B, T, D] — attention-weighted aggregation.
    """
    values = blocks + [partial_block]
    V = torch.stack(values, dim=0)  # [N+1, B, T, D]
    K = norm(V)
    logits = proj(K)  # [N+1, B, T]
    weights = logits.softmax(dim=0)
    h = torch.einsum("n b t, n b t d -> b t d", weights, V)
    return h


# ── Convenience wrappers ─────────────────────────────────────────────────────


class AttnResTransformer(nn.Module):
    """Minimal transformer with Block Attention Residuals.

    A self-contained demonstration model for testing and experimentation.
    Uses multi-head self-attention + feedforward MLP with Block AttnRes.
    """

    def __init__(
        self,
        dim: int = 512,
        num_layers: int = 12,
        num_heads: int = 8,
        mlp_ratio: float = 4.0,
        block_size: int = 8,
        dropout: float = 0.0,
        vocab_size: int = 32000,
        max_seq_len: int = 2048,
    ):
        super().__init__()
        self.dim = dim
        self.num_layers = num_layers
        self.block_size = block_size

        self.tok_emb = nn.Embedding(vocab_size, dim)
        self.pos_emb = nn.Embedding(max_seq_len, dim)
        self.emb_norm = RMSNorm(dim)

        self.layers = nn.ModuleList()
        for i in range(num_layers):
            attn = nn.MultiheadAttention(
                dim, num_heads, dropout=dropout, batch_first=True
            )
            mlp = nn.Sequential(
                nn.Linear(dim, int(dim * mlp_ratio)),
                nn.GELU(),
                nn.Linear(int(dim * mlp_ratio), dim),
                nn.Dropout(dropout),
            )
            layer = BlockAttnResLayer(
                dim=dim,
                attn=_MHAWrapper(attn),
                mlp=mlp,
                layer_number=i,
                block_size=block_size,
            )
            self.layers.append(layer)

        self.final_norm = RMSNorm(dim)
        self.lm_head = nn.Linear(dim, vocab_size, bias=False)

        # Weight tying
        self.lm_head.weight = self.tok_emb.weight

        self._init_weights()

    def _init_weights(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(
        self,
        input_ids: Tensor,
        attention_mask: Optional[Tensor] = None,
    ) -> Tensor:
        """Forward pass.

        Args:
            input_ids: [B, T] token indices.
            attention_mask: [B, T] optional mask (1 = attend, 0 = ignore).

        Returns:
            logits: [B, T, vocab_size]
        """
        B, T = input_ids.shape
        positions = torch.arange(T, device=input_ids.device).unsqueeze(0)

        x = self.tok_emb(input_ids) + self.pos_emb(positions)
        x = self.emb_norm(x)

        # Initialize blocks with the embedding as the first block
        blocks: list[Tensor] = [x]
        partial_block: Optional[Tensor] = None

        # Build causal mask for self-attention
        causal_mask = torch.triu(
            torch.ones(T, T, device=x.device, dtype=torch.bool), diagonal=1
        )

        for layer in self.layers:
            x, blocks, partial_block = layer(
                x, blocks, partial_block, attn_mask=causal_mask
            )

        x = self.final_norm(x)
        logits = self.lm_head(x)
        return logits

    def count_parameters(self) -> dict[str, int]:
        """Count parameters by component."""
        counts = {
            "embedding": sum(p.numel() for p in self.tok_emb.parameters())
            + sum(p.numel() for p in self.pos_emb.parameters()),
            "attn_res": 0,
            "attention": 0,
            "mlp": 0,
            "norms": 0,
        }
        for layer in self.layers:
            counts["attn_res"] += sum(
                p.numel()
                for n, p in layer.named_parameters()
                if "res_proj" in n or "res_norm" in n
            )
            counts["attention"] += sum(
                p.numel() for n, p in layer.named_parameters() if "attn." in n
            )
            counts["mlp"] += sum(
                p.numel() for n, p in layer.named_parameters() if "mlp." in n
            )
            counts["norms"] += sum(
                p.numel()
                for n, p in layer.named_parameters()
                if "norm" in n and "res_norm" not in n
            )
        counts["total"] = sum(p.numel() for p in self.parameters())
        counts["attn_res_pct"] = (
            f"{counts['attn_res'] / counts['total'] * 100:.2f}%"
            if counts["total"]
            else "0%"
        )
        return counts


class _MHAWrapper(nn.Module):
    """Wraps nn.MultiheadAttention to match the expected interface."""

    def __init__(self, mha: nn.MultiheadAttention):
        super().__init__()
        self.mha = mha

    def forward(self, x: Tensor, attn_mask: Optional[Tensor] = None, **kwargs) -> Tensor:
        out, _ = self.mha(x, x, x, attn_mask=attn_mask, is_causal=False)
        return out


# ── Retrofit utility ──────────────────────────────────────────────────────────


def retrofit_block_attn_res(
    model: nn.Module,
    dim: int,
    layer_attr: str = "layers",
    block_size: int = 8,
) -> nn.Module:
    """Retrofit Block AttnRes onto an existing transformer model.

    Adds AttnRes projection and norm parameters to each layer.
    The caller must modify the forward pass to use block_attn_res().

    Args:
        model: Transformer model with a list of layers.
        dim: Hidden dimension.
        layer_attr: Name of the attribute holding the layer list.
        block_size: Number of sub-layers per block.

    Returns:
        The model with AttnRes parameters added to each layer.
    """
    layers = getattr(model, layer_attr)
    for i, layer in enumerate(layers):
        layer.attn_res_proj = AttnResProjection(dim)
        layer.attn_res_norm = RMSNorm(dim)
        layer.mlp_res_proj = AttnResProjection(dim)
        layer.mlp_res_norm = RMSNorm(dim)
        layer._attn_res_layer_number = i
        layer._attn_res_block_size = block_size
    return model
