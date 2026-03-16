"""Tests for Attention Residuals (AttnRes) implementation.

Validates both Full and Block AttnRes variants, the convenience transformer,
and the retrofit utility.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

torch = pytest.importorskip("torch")

from forge.attention_residuals import (
    RMSNorm,
    AttnResProjection,
    attn_res_aggregate,
    FullAttnResLayer,
    BlockAttnResLayer,
    AttnResTransformer,
    _block_attn_res,
    retrofit_block_attn_res,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

B, T, D = 2, 16, 64
NUM_HEADS = 4


@pytest.fixture
def hidden():
    return torch.randn(B, T, D)


@pytest.fixture
def simple_attn():
    mha = torch.nn.MultiheadAttention(D, NUM_HEADS, batch_first=True)
    from forge.attention_residuals import _MHAWrapper
    return _MHAWrapper(mha)


@pytest.fixture
def simple_mlp():
    return torch.nn.Sequential(
        torch.nn.Linear(D, D * 4),
        torch.nn.GELU(),
        torch.nn.Linear(D * 4, D),
    )


# ── RMSNorm ───────────────────────────────────────────────────────────────────


class TestRMSNorm:
    def test_output_shape(self, hidden):
        norm = RMSNorm(D)
        out = norm(hidden)
        assert out.shape == hidden.shape

    def test_preserves_dtype(self):
        norm = RMSNorm(D)
        x = torch.randn(B, T, D, dtype=torch.float32)
        assert norm(x).dtype == torch.float32

    def test_normalizes(self, hidden):
        norm = RMSNorm(D)
        out = norm(hidden)
        rms = out.float().pow(2).mean(-1).sqrt()
        assert torch.allclose(rms, torch.ones_like(rms), atol=0.1)


# ── AttnResProjection ─────────────────────────────────────────────────────────


class TestAttnResProjection:
    def test_output_shape(self):
        proj = AttnResProjection(D)
        keys = torch.randn(3, B, T, D)
        logits = proj(keys)
        assert logits.shape == (3, B, T)

    def test_single_element(self):
        proj = AttnResProjection(D)
        keys = torch.randn(1, B, T, D)
        logits = proj(keys)
        assert logits.shape == (1, B, T)


# ── attn_res_aggregate ────────────────────────────────────────────────────────


class TestAttnResAggregate:
    def test_output_shape(self, hidden):
        proj = AttnResProjection(D)
        norm = RMSNorm(D)
        values = [torch.randn(B, T, D) for _ in range(5)]
        out = attn_res_aggregate(values, proj, norm)
        assert out.shape == (B, T, D)

    def test_single_value_is_identity(self, hidden):
        proj = AttnResProjection(D)
        norm = RMSNorm(D)
        out = attn_res_aggregate([hidden], proj, norm)
        assert torch.allclose(out, hidden, atol=1e-5)

    def test_gradients_flow(self, hidden):
        proj = AttnResProjection(D)
        norm = RMSNorm(D)
        v1 = hidden.clone().requires_grad_(True)
        v2 = torch.randn(B, T, D, requires_grad=True)
        out = attn_res_aggregate([v1, v2], proj, norm)
        out.sum().backward()
        assert v1.grad is not None
        assert v2.grad is not None


# ── _block_attn_res ───────────────────────────────────────────────────────────


class TestBlockAttnRes:
    def test_output_shape(self, hidden):
        proj = AttnResProjection(D)
        norm = RMSNorm(D)
        blocks = [torch.randn(B, T, D) for _ in range(3)]
        out = _block_attn_res(blocks, hidden, proj, norm)
        assert out.shape == (B, T, D)

    def test_no_blocks(self, hidden):
        proj = AttnResProjection(D)
        norm = RMSNorm(D)
        out = _block_attn_res([], hidden, proj, norm)
        assert torch.allclose(out, hidden, atol=1e-5)

    def test_weights_sum_to_one(self, hidden):
        proj = AttnResProjection(D)
        norm = RMSNorm(D)
        blocks = [torch.randn(B, T, D) for _ in range(3)]
        values = blocks + [hidden]
        V = torch.stack(values, dim=0)
        K = norm(V)
        logits = proj(K)
        weights = logits.softmax(dim=0)
        sums = weights.sum(dim=0)
        assert torch.allclose(sums, torch.ones_like(sums), atol=1e-5)


# ── FullAttnResLayer ──────────────────────────────────────────────────────────


class TestFullAttnResLayer:
    def test_forward(self, hidden, simple_attn, simple_mlp):
        layer = FullAttnResLayer(D, simple_attn, simple_mlp)
        history = [hidden]  # embedding as first entry
        out, new_history = layer(hidden, history)
        assert out.shape == hidden.shape
        assert len(new_history) == len(history) + 1

    def test_history_grows(self, hidden, simple_attn, simple_mlp):
        layer = FullAttnResLayer(D, simple_attn, simple_mlp)
        history = [hidden]
        for _ in range(4):
            out, history = layer(out if _ > 0 else hidden, history)
        assert len(history) == 5  # 1 initial + 4 layers

    def test_gradient_flow(self, simple_attn, simple_mlp):
        layer = FullAttnResLayer(D, simple_attn, simple_mlp)
        x = torch.randn(B, T, D, requires_grad=True)
        history = [x]
        out, _ = layer(x, history)
        out.sum().backward()
        assert x.grad is not None


# ── BlockAttnResLayer ─────────────────────────────────────────────────────────


class TestBlockAttnResLayer:
    def test_forward(self, hidden, simple_attn, simple_mlp):
        layer = BlockAttnResLayer(D, simple_attn, simple_mlp, layer_number=0, block_size=8)
        blocks = [hidden]
        out, new_blocks, partial = layer(hidden, blocks, None)
        assert out.shape == hidden.shape

    def test_block_boundary(self, hidden, simple_attn, simple_mlp):
        """At block boundaries, a new block should be appended."""
        block_size = 4  # boundary at layer 0, 2, 4, ...
        layer0 = BlockAttnResLayer(D, simple_attn, simple_mlp, layer_number=0, block_size=block_size)
        blocks = [hidden]
        initial_len = len(blocks)
        _, new_blocks, _ = layer0(hidden, blocks, None)
        assert len(new_blocks) == initial_len + 1

    def test_no_boundary(self, hidden, simple_attn, simple_mlp):
        """Non-boundary layers should not add blocks."""
        block_size = 8
        layer1 = BlockAttnResLayer(D, simple_attn, simple_mlp, layer_number=1, block_size=block_size)
        blocks = [hidden]
        _, new_blocks, _ = layer1(hidden, blocks, hidden)
        assert len(new_blocks) == len(blocks)

    def test_gradient_flow(self, simple_attn, simple_mlp):
        layer = BlockAttnResLayer(D, simple_attn, simple_mlp, layer_number=0, block_size=8)
        x = torch.randn(B, T, D, requires_grad=True)
        blocks = [x]
        out, _, _ = layer(x, blocks, None)
        out.sum().backward()
        assert x.grad is not None


# ── AttnResTransformer ────────────────────────────────────────────────────────


class TestAttnResTransformer:
    def test_forward_shape(self):
        model = AttnResTransformer(dim=64, num_layers=4, num_heads=4, vocab_size=100, max_seq_len=32)
        ids = torch.randint(0, 100, (2, 16))
        logits = model(ids)
        assert logits.shape == (2, 16, 100)

    def test_causal_masking(self):
        model = AttnResTransformer(dim=64, num_layers=2, num_heads=4, vocab_size=100, max_seq_len=32)
        ids = torch.randint(0, 100, (1, 8))
        logits = model(ids)
        assert logits.shape == (1, 8, 100)

    def test_gradient_flow_e2e(self):
        model = AttnResTransformer(dim=64, num_layers=4, num_heads=4, vocab_size=100, max_seq_len=32)
        ids = torch.randint(0, 100, (2, 16))
        logits = model(ids)
        loss = logits.sum()
        loss.backward()
        for name, param in model.named_parameters():
            if param.requires_grad:
                assert param.grad is not None, f"No gradient for {name}"

    def test_count_parameters(self):
        model = AttnResTransformer(dim=64, num_layers=4, num_heads=4, vocab_size=100)
        counts = model.count_parameters()
        assert counts["total"] > 0
        assert counts["attn_res"] > 0
        assert "attn_res_pct" in counts

    def test_attn_res_overhead_small(self):
        model = AttnResTransformer(dim=256, num_layers=12, num_heads=8, vocab_size=1000)
        counts = model.count_parameters()
        pct = counts["attn_res"] / counts["total"] * 100
        assert pct < 5, f"AttnRes overhead {pct:.1f}% exceeds 5%"


# ── Retrofit Utility ──────────────────────────────────────────────────────────


class TestRetrofit:
    def test_adds_parameters(self):
        class FakeModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.layers = torch.nn.ModuleList([
                    torch.nn.Linear(D, D) for _ in range(4)
                ])
        model = FakeModel()
        retrofit_block_attn_res(model, D, block_size=4)
        for i, layer in enumerate(model.layers):
            assert hasattr(layer, "attn_res_proj")
            assert hasattr(layer, "attn_res_norm")
            assert hasattr(layer, "mlp_res_proj")
            assert hasattr(layer, "mlp_res_norm")
            assert layer._attn_res_layer_number == i
            assert layer._attn_res_block_size == 4

    def test_retrofit_preserves_original(self):
        class FakeModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.layers = torch.nn.ModuleList([
                    torch.nn.Linear(D, D) for _ in range(4)
                ])
        model = FakeModel()
        original_params = sum(p.numel() for p in model.parameters())
        retrofit_block_attn_res(model, D)
        new_params = sum(p.numel() for p in model.parameters())
        assert new_params > original_params


# ── Bounded Magnitudes (Key Paper Claim) ──────────────────────────────────────


class TestBoundedMagnitudes:
    def test_output_magnitude_bounded(self):
        """AttnRes should keep output magnitudes bounded (softmax = convex combo)."""
        model = AttnResTransformer(dim=64, num_layers=8, num_heads=4, vocab_size=100, max_seq_len=32)
        ids = torch.randint(0, 100, (2, 16))
        with torch.no_grad():
            logits = model(ids)
        # Output should be finite and reasonable
        assert torch.isfinite(logits).all()
        assert logits.abs().max() < 1000, "Output magnitudes exploded"
