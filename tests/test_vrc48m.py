"""Tests for VRC-48M: Topological Media Provenance engine."""

import json
import math
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from vortexchain.vrc48m import (
    # Constants
    SFP_DIM,
    SPATIAL_FEATURES,
    FREQUENCY_FEATURES,
    TEMPORAL_FEATURES,
    CHROMATIC_FEATURES,
    DEFAULT_CHUNK_SIZE,
    WRAPPING_MODULUS,
    STABILIZATION_EPSILON,
    # Feature extraction
    extract_spatial_features,
    extract_frequency_features,
    extract_temporal_features,
    extract_chromatic_features,
    extract_sfp,
    # Normalization
    normalize_sfp,
    # Topological hashing
    sfp_to_manifold,
    compute_tmh,
    # Merkle tree
    _topo_hash_pair,
    build_merkle_tree,
    find_divergent_chunks,
    # Data classes
    ChunkResult,
    MediaAnalysis,
    MediaAnchor,
    # Verification
    VerificationStatus,
    TamperedChunk,
    VerificationResult,
    classify_spectral_distance,
    # Image analysis
    analyze_image,
    # Streaming
    StreamingVRC48M,
)
from vortexchain.manifold import MANIFOLD_DIM, NUM_EMBEDDED_SPHERES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_frame(width=128, height=128, color=(128, 128, 128), noise=0):
    """Create a synthetic BGR frame."""
    frame = np.full((height, width, 3), color, dtype=np.uint8)
    if noise:
        rng = np.random.RandomState(42)
        frame = np.clip(
            frame.astype(np.int16) + rng.randint(-noise, noise + 1, frame.shape),
            0, 255,
        ).astype(np.uint8)
    return frame


def make_gradient_frame(width=128, height=128):
    """Create a frame with horizontal gradient for detectable spatial features."""
    grad = np.linspace(0, 255, width, dtype=np.uint8)
    gray = np.tile(grad, (height, 1))
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def make_test_image(path, width=128, height=128):
    """Write a test image to disk and return the path."""
    frame = make_gradient_frame(width, height)
    cv2.imwrite(str(path), frame)
    return str(path)


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------

class TestConstants:
    def test_sfp_dim_equals_manifold_dim(self):
        assert SFP_DIM == MANIFOLD_DIM == 48

    def test_feature_dimensions_sum_to_sfp(self):
        assert SPATIAL_FEATURES + FREQUENCY_FEATURES + TEMPORAL_FEATURES + CHROMATIC_FEATURES == SFP_DIM

    def test_individual_feature_dimensions(self):
        assert SPATIAL_FEATURES == 16
        assert FREQUENCY_FEATURES == 16
        assert TEMPORAL_FEATURES == 8
        assert CHROMATIC_FEATURES == 8

    def test_wrapping_modulus_is_prime(self):
        n = WRAPPING_MODULUS
        assert n > 1
        for i in range(2, int(n ** 0.5) + 1):
            assert n % i != 0, f"{n} is divisible by {i}"


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

class TestExtractSpatialFeatures:
    def test_output_shape(self):
        gray = cv2.cvtColor(make_frame(), cv2.COLOR_BGR2GRAY)
        features = extract_spatial_features(gray)
        assert features.shape == (SPATIAL_FEATURES,)
        assert features.dtype == np.float64

    def test_deterministic(self):
        gray = cv2.cvtColor(make_gradient_frame(), cv2.COLOR_BGR2GRAY)
        a = extract_spatial_features(gray)
        b = extract_spatial_features(gray)
        np.testing.assert_array_equal(a, b)

    def test_different_images_differ(self):
        gray1 = cv2.cvtColor(make_frame(color=(50, 50, 50), noise=30), cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(make_gradient_frame(), cv2.COLOR_BGR2GRAY)
        f1 = extract_spatial_features(gray1)
        f2 = extract_spatial_features(gray2)
        assert not np.allclose(f1, f2)


class TestExtractFrequencyFeatures:
    def test_output_shape(self):
        gray = cv2.cvtColor(make_frame(), cv2.COLOR_BGR2GRAY)
        features = extract_frequency_features(gray)
        assert features.shape == (FREQUENCY_FEATURES,)
        assert features.dtype == np.float64

    def test_deterministic(self):
        gray = cv2.cvtColor(make_gradient_frame(), cv2.COLOR_BGR2GRAY)
        a = extract_frequency_features(gray)
        b = extract_frequency_features(gray)
        np.testing.assert_array_equal(a, b)

    def test_uniform_image_has_small_ac(self):
        """A solid-color image should have near-zero AC (non-DC) coefficients."""
        gray = np.full((128, 128), 128, dtype=np.uint8)
        features = extract_frequency_features(gray)
        assert np.max(np.abs(features)) < 0.01


class TestExtractTemporalFeatures:
    def test_first_frame_returns_zeros(self):
        gray = cv2.cvtColor(make_frame(), cv2.COLOR_BGR2GRAY)
        features = extract_temporal_features(None, gray)
        assert features.shape == (TEMPORAL_FEATURES,)
        np.testing.assert_array_equal(features, np.zeros(TEMPORAL_FEATURES))

    def test_output_shape_with_prev(self):
        gray1 = cv2.cvtColor(make_frame(color=(100, 100, 100)), cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(make_frame(color=(200, 200, 200)), cv2.COLOR_BGR2GRAY)
        features = extract_temporal_features(gray1, gray2)
        assert features.shape == (TEMPORAL_FEATURES,)
        assert features.dtype == np.float64

    def test_identical_frames_low_motion(self):
        gray = cv2.cvtColor(make_frame(), cv2.COLOR_BGR2GRAY)
        features = extract_temporal_features(gray, gray.copy())
        # Mean flow and temporal energy should be near zero
        assert features[0] < 1.0  # mean flow magnitude
        assert features[6] < 1.0  # temporal energy


class TestExtractChromaticFeatures:
    def test_output_shape(self):
        frame = make_frame()
        features = extract_chromatic_features(frame)
        assert features.shape == (CHROMATIC_FEATURES,)
        assert features.dtype == np.float64

    def test_deterministic(self):
        frame = make_gradient_frame()
        a = extract_chromatic_features(frame)
        b = extract_chromatic_features(frame)
        np.testing.assert_array_equal(a, b)


class TestExtractSFP:
    def test_full_sfp_shape(self):
        frame = make_gradient_frame()
        sfp = extract_sfp(frame, None)
        assert sfp.shape == (SFP_DIM,)

    def test_sfp_with_prev_gray(self):
        frame1 = make_frame(color=(100, 100, 100))
        frame2 = make_frame(color=(150, 150, 150))
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        sfp = extract_sfp(frame2, gray1)
        assert sfp.shape == (SFP_DIM,)

    def test_deterministic(self):
        frame = make_gradient_frame()
        a = extract_sfp(frame, None)
        b = extract_sfp(frame, None)
        np.testing.assert_array_equal(a, b)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalizeSFP:
    def test_output_range(self):
        sfp = np.random.RandomState(0).randn(SFP_DIM) * 100
        norm = normalize_sfp(sfp)
        assert norm.shape == (SFP_DIM,)
        assert np.all(norm >= 0.0)
        assert np.all(norm <= 1.0)

    def test_zero_input(self):
        sfp = np.zeros(SFP_DIM)
        norm = normalize_sfp(sfp)
        # tanh(0) = 0 => (0 + 1) / 2 = 0.5
        np.testing.assert_allclose(norm, 0.5, atol=1e-10)

    def test_large_values_saturate_near_boundaries(self):
        sfp = np.full(SFP_DIM, 1e6)
        norm = normalize_sfp(sfp)
        # Should be very close to 1.0
        assert np.all(norm > 0.99)

    def test_negative_values(self):
        sfp = np.full(SFP_DIM, -1e6)
        norm = normalize_sfp(sfp)
        assert np.all(norm < 0.01)


# ---------------------------------------------------------------------------
# Topological mapping
# ---------------------------------------------------------------------------

class TestSFPToManifold:
    def test_returns_valid_manifold(self):
        sfp_norm = np.full(SFP_DIM, 0.5)
        manifold = sfp_to_manifold(sfp_norm)
        assert len(manifold.components) == MANIFOLD_DIM
        assert len(manifold.wrapping_numbers) == NUM_EMBEDDED_SPHERES

    def test_components_in_range(self):
        sfp_norm = np.random.RandomState(1).rand(SFP_DIM)
        manifold = sfp_to_manifold(sfp_norm)
        for c in manifold.components:
            assert -1.0 < c < 1.0  # tanh output

    def test_wrapping_numbers_bounded(self):
        sfp_norm = np.random.RandomState(2).rand(SFP_DIM)
        manifold = sfp_to_manifold(sfp_norm)
        for wn in manifold.wrapping_numbers:
            assert 0 <= wn.value < WRAPPING_MODULUS

    def test_deterministic(self):
        sfp_norm = np.random.RandomState(3).rand(SFP_DIM)
        m1 = sfp_to_manifold(sfp_norm)
        m2 = sfp_to_manifold(sfp_norm)
        assert m1.components == m2.components
        for a, b in zip(m1.wrapping_numbers, m2.wrapping_numbers):
            assert a.value == b.value

    def test_different_inputs_different_manifolds(self):
        a = sfp_to_manifold(np.full(SFP_DIM, 0.2))
        b = sfp_to_manifold(np.full(SFP_DIM, 0.8))
        assert a.components != b.components


class TestComputeTMH:
    def test_returns_spectrum_and_digest(self):
        sfp_norm = np.random.RandomState(4).rand(SFP_DIM)
        spectrum, digest = compute_tmh(sfp_norm)
        assert len(spectrum) == NUM_EMBEDDED_SPHERES
        assert isinstance(digest, bytes)
        assert len(digest) == NUM_EMBEDDED_SPHERES * 2  # 2 bytes per wrapping number

    def test_deterministic(self):
        sfp_norm = np.random.RandomState(5).rand(SFP_DIM)
        s1, d1 = compute_tmh(sfp_norm)
        s2, d2 = compute_tmh(sfp_norm)
        assert s1 == s2
        assert d1 == d2


# ---------------------------------------------------------------------------
# Merkle tree
# ---------------------------------------------------------------------------

class TestBuildMerkleTree:
    def test_single_digest(self):
        digest = b"\x01" * 48
        root, levels = build_merkle_tree([digest])
        assert root == digest
        assert len(levels) == 1

    def test_two_digests(self):
        d1 = b"\x01" * 48
        d2 = b"\x02" * 48
        root, levels = build_merkle_tree([d1, d2])
        assert len(root) > 0
        assert len(levels) == 2
        expected_root = _topo_hash_pair(d1, d2)
        assert root == expected_root

    def test_power_of_two(self):
        digests = [bytes([i]) * 48 for i in range(4)]
        root, levels = build_merkle_tree(digests)
        assert root is not None
        assert len(levels) == 3  # 4 -> 2 -> 1

    def test_non_power_of_two_pads(self):
        digests = [bytes([i]) * 48 for i in range(3)]
        root, levels = build_merkle_tree(digests)
        # 3 gets padded to 4
        assert len(levels[0]) == 4
        assert len(levels) == 3

    def test_empty_input(self):
        root, levels = build_merkle_tree([])
        assert root == b"\x00" * 48

    def test_deterministic(self):
        digests = [bytes([i]) * 48 for i in range(5)]
        r1, _ = build_merkle_tree(digests)
        r2, _ = build_merkle_tree(digests)
        assert r1 == r2


class TestFindDivergentChunks:
    def test_all_match(self):
        digests = [b"\x01" * 48, b"\x02" * 48]
        assert find_divergent_chunks(digests, digests) == []

    def test_one_differs(self):
        computed = [b"\x01" * 48, b"\x02" * 48, b"\x03" * 48]
        anchor = [b"\x01" * 48, b"\xFF" * 48, b"\x03" * 48]
        assert find_divergent_chunks(computed, anchor) == [1]

    def test_all_differ(self):
        computed = [b"\x01" * 48, b"\x02" * 48]
        anchor = [b"\x03" * 48, b"\x04" * 48]
        assert find_divergent_chunks(computed, anchor) == [0, 1]

    def test_different_lengths_truncates(self):
        computed = [b"\x01" * 48, b"\x02" * 48, b"\x03" * 48]
        anchor = [b"\x01" * 48, b"\x02" * 48]
        # zip stops at shorter
        assert find_divergent_chunks(computed, anchor) == []


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassifySpectralDistance:
    def test_minor(self):
        assert classify_spectral_distance(0) == "MINOR_EDIT"
        assert classify_spectral_distance(1) == "MINOR_EDIT"
        assert classify_spectral_distance(2) == "MINOR_EDIT"

    def test_significant(self):
        assert classify_spectral_distance(3) == "SIGNIFICANT_EDIT"
        assert classify_spectral_distance(6) == "SIGNIFICANT_EDIT"

    def test_major(self):
        assert classify_spectral_distance(7) == "MAJOR_EDIT"
        assert classify_spectral_distance(12) == "MAJOR_EDIT"

    def test_regenerated(self):
        assert classify_spectral_distance(13) == "REGENERATED"
        assert classify_spectral_distance(24) == "REGENERATED"


# ---------------------------------------------------------------------------
# MediaAnchor serialization
# ---------------------------------------------------------------------------

class TestMediaAnchor:
    def _make_anchor(self):
        return MediaAnchor(
            version=1,
            standard="VRC-48M",
            file_path="test.mp4",
            frame_count=60,
            fps=30.0,
            width=1920,
            height=1080,
            duration_ms=2000,
            chunk_size=30,
            video_merkle_root="aabbccdd",
            chunk_spectra=[[1, 2, 3]],
            chunk_digests=["deadbeef"],
            sample_spectra=[[1, 2, 3]],
            timestamp=1000000.0,
            processing_time_ms=500.0,
        )

    def test_to_json_roundtrip(self):
        anchor = self._make_anchor()
        json_str = anchor.to_json()
        restored = MediaAnchor.from_json(json_str)
        assert restored.file_path == anchor.file_path
        assert restored.frame_count == anchor.frame_count
        assert restored.fps == anchor.fps
        assert restored.video_merkle_root == anchor.video_merkle_root
        assert restored.chunk_spectra == anchor.chunk_spectra
        assert restored.chunk_digests == anchor.chunk_digests

    def test_save_and_load(self, tmp_path):
        anchor = self._make_anchor()
        path = str(tmp_path / "anchor.json")
        anchor.save(path)
        loaded = MediaAnchor.load(path)
        assert loaded.standard == "VRC-48M"
        assert loaded.width == 1920
        assert loaded.chunk_spectra == [[1, 2, 3]]

    def test_json_is_valid(self):
        anchor = self._make_anchor()
        parsed = json.loads(anchor.to_json())
        assert parsed["standard"] == "VRC-48M"
        assert isinstance(parsed["chunk_spectra"], list)


# ---------------------------------------------------------------------------
# VerificationResult
# ---------------------------------------------------------------------------

class TestVerificationResult:
    def test_summary_authentic(self):
        result = VerificationResult(
            status=VerificationStatus.AUTHENTIC,
            confidence=0.999,
            merkle_match=True,
            total_chunks=10,
            matching_chunks=10,
        )
        summary = result.summary()
        assert "AUTHENTIC" in summary
        assert "99.9%" in summary
        assert "10/10" in summary

    def test_summary_with_tampered_chunks(self):
        result = VerificationResult(
            status=VerificationStatus.TAMPERED,
            confidence=0.5,
            merkle_match=False,
            total_chunks=4,
            matching_chunks=2,
            tampered_chunks=[
                TamperedChunk(
                    chunk_index=1,
                    frame_start=30,
                    frame_end=59,
                    time_start_ms=1000.0,
                    time_end_ms=2000.0,
                    spectral_distance=15,
                    classification="REGENERATED",
                ),
            ],
        )
        summary = result.summary()
        assert "TAMPERED" in summary
        assert "Chunk 1" in summary
        assert "REGENERATED" in summary


# ---------------------------------------------------------------------------
# Image analysis (integration, uses real cv2)
# ---------------------------------------------------------------------------

class TestAnalyzeImage:
    def test_analyze_gradient_image(self, tmp_path):
        img_path = make_test_image(tmp_path / "test.png")
        analysis = analyze_image(img_path)
        assert analysis.frame_count == 1
        assert analysis.fps == 0.0
        assert analysis.width == 128
        assert analysis.height == 128
        assert len(analysis.chunks) == 1
        assert analysis.chunks[0].chunk_index == 0
        assert len(analysis.merkle_root) > 0

    def test_deterministic_image_analysis(self, tmp_path):
        img_path = make_test_image(tmp_path / "test.png")
        a1 = analyze_image(img_path)
        a2 = analyze_image(img_path)
        assert a1.merkle_root == a2.merkle_root
        assert a1.chunks[0].spectrum == a2.chunks[0].spectrum

    def test_invalid_image_raises(self):
        with pytest.raises(ValueError, match="Cannot open image"):
            analyze_image("/nonexistent/fake.png")

    def test_anchor_from_analysis(self, tmp_path):
        img_path = make_test_image(tmp_path / "test.png")
        analysis = analyze_image(img_path)
        anchor = MediaAnchor.from_analysis(analysis)
        assert anchor.standard == "VRC-48M"
        assert anchor.frame_count == 1
        assert len(anchor.chunk_spectra) == 1
        assert len(anchor.chunk_digests) == 1
        assert anchor.video_merkle_root == analysis.merkle_root.hex()

    def test_different_images_different_roots(self, tmp_path):
        img1 = make_test_image(tmp_path / "a.png", width=128, height=128)
        # Create a second distinct image
        frame2 = make_frame(color=(30, 200, 80), noise=40)
        img2 = str(tmp_path / "b.png")
        cv2.imwrite(img2, frame2)

        a1 = analyze_image(img1)
        a2 = analyze_image(img2)
        assert a1.merkle_root != a2.merkle_root


# ---------------------------------------------------------------------------
# End-to-end: anchor → verify round-trip with images
# ---------------------------------------------------------------------------

class TestImageVerifyRoundTrip:
    def test_self_verify_authentic(self, tmp_path):
        """An image verified against its own anchor should be AUTHENTIC."""
        from vortexchain.vrc48m import verify_media

        img_path = make_test_image(tmp_path / "original.png")
        analysis = analyze_image(img_path)
        anchor = MediaAnchor.from_analysis(analysis)

        result = verify_media(img_path, anchor)
        assert result.status == VerificationStatus.AUTHENTIC
        assert result.merkle_match is True
        assert result.confidence == pytest.approx(0.999)

    def test_modified_image_not_authentic(self, tmp_path):
        """A modified image should NOT match the original anchor."""
        from vortexchain.vrc48m import verify_media

        img_path = make_test_image(tmp_path / "original.png")
        analysis = analyze_image(img_path)
        anchor = MediaAnchor.from_analysis(analysis)

        # Create a different image at a new path
        modified = make_frame(color=(255, 0, 0), noise=50)
        modified_path = str(tmp_path / "modified.png")
        cv2.imwrite(modified_path, modified)

        result = verify_media(modified_path, anchor)
        assert result.status != VerificationStatus.AUTHENTIC
        assert result.merkle_match is False

    def test_quick_verify_self(self, tmp_path):
        """Quick verify of an image against its own anchor."""
        from vortexchain.vrc48m import quick_verify

        img_path = make_test_image(tmp_path / "original.png")
        analysis = analyze_image(img_path)
        anchor = MediaAnchor.from_analysis(analysis)

        result = quick_verify(img_path, anchor)
        assert result.status == VerificationStatus.AUTHENTIC
        assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# compare_media
# ---------------------------------------------------------------------------

class TestCompareMedia:
    def test_identical_images(self, tmp_path):
        from vortexchain.vrc48m import compare_media

        img_path = make_test_image(tmp_path / "same.png")
        result = compare_media(img_path, img_path)
        assert result.status == VerificationStatus.AUTHENTIC

    def test_different_images(self, tmp_path):
        from vortexchain.vrc48m import compare_media

        img1 = make_test_image(tmp_path / "a.png")
        frame2 = make_frame(color=(0, 0, 255), noise=60)
        img2 = str(tmp_path / "b.png")
        cv2.imwrite(img2, frame2)

        result = compare_media(img1, img2)
        assert result.merkle_match is False


# ---------------------------------------------------------------------------
# StreamingVRC48M
# ---------------------------------------------------------------------------

class TestStreamingVRC48M:
    def test_no_frames_finalize(self):
        """Finalizing with zero frames should produce an empty analysis."""
        stream = StreamingVRC48M(chunk_size=5)
        analysis = stream.finalize()
        assert analysis.frame_count == 0
        assert len(analysis.chunks) == 0
        assert analysis.merkle_root == b"\x00" * 48

    def test_chunk_emitted_at_boundary(self):
        """process_frame returns ChunkResult exactly at chunk_size."""
        chunk_size = 3
        stream = StreamingVRC48M(chunk_size=chunk_size)
        results = []
        for i in range(chunk_size):
            frame = make_frame(color=(50 + i * 20, 100, 100))
            result = stream.process_frame(frame)
            results.append(result)

        # Only the last frame should have emitted a chunk
        assert all(r is None for r in results[:-1])
        assert results[-1] is not None
        assert isinstance(results[-1], ChunkResult)
        assert results[-1].chunk_index == 0

    def test_multiple_chunks(self):
        """Feeding 2*chunk_size frames should produce 2 chunks."""
        chunk_size = 3
        stream = StreamingVRC48M(chunk_size=chunk_size)
        emitted = []
        for i in range(chunk_size * 2):
            frame = make_frame(color=(40 + i * 10, 80, 120))
            result = stream.process_frame(frame)
            if result is not None:
                emitted.append(result)

        assert len(emitted) == 2
        assert emitted[0].chunk_index == 0
        assert emitted[1].chunk_index == 1

    def test_flush_partial_chunk(self):
        """Flush should emit a partial chunk for trailing frames."""
        chunk_size = 5
        stream = StreamingVRC48M(chunk_size=chunk_size)
        # Feed 3 frames (less than chunk_size)
        for i in range(3):
            stream.process_frame(make_frame(color=(60 + i * 30, 100, 100)))

        result = stream.flush()
        assert result is not None
        assert result.chunk_index == 0
        assert result.frame_start == 0
        assert result.frame_end == 2

    def test_flush_no_pending(self):
        """Flush with no buffered frames returns None."""
        chunk_size = 2
        stream = StreamingVRC48M(chunk_size=chunk_size)
        # Feed exactly chunk_size frames so buffer is empty
        for i in range(chunk_size):
            stream.process_frame(make_frame(color=(100 + i * 10, 100, 100)))
        assert stream.flush() is None

    def test_finalize_flushes_trailing(self):
        """Finalize should include a partial trailing chunk."""
        chunk_size = 5
        stream = StreamingVRC48M(chunk_size=chunk_size)
        # 7 frames = 1 full chunk (5) + 1 partial (2)
        for i in range(7):
            stream.process_frame(make_frame(color=(50 + i * 10, 80, 120)))

        analysis = stream.finalize()
        assert analysis.frame_count == 7
        assert len(analysis.chunks) == 2
        assert analysis.chunks[0].frame_end - analysis.chunks[0].frame_start + 1 == chunk_size
        assert analysis.chunks[1].frame_end - analysis.chunks[1].frame_start + 1 == 2

    def test_finalize_produces_valid_analysis(self):
        """Finalize should produce a complete MediaAnalysis."""
        chunk_size = 3
        stream = StreamingVRC48M(chunk_size=chunk_size, fps=30.0)
        for i in range(6):
            stream.process_frame(make_gradient_frame())

        analysis = stream.finalize()
        assert analysis.fps == 30.0
        assert analysis.chunk_size == chunk_size
        assert len(analysis.merkle_root) > 0
        assert len(analysis.merkle_levels) > 0
        assert len(analysis.sample_spectra) == 4

    def test_finalize_twice_raises(self):
        stream = StreamingVRC48M(chunk_size=3)
        stream.process_frame(make_frame())
        stream.finalize()
        with pytest.raises(RuntimeError, match="already called"):
            stream.finalize()

    def test_process_frame_after_finalize_raises(self):
        stream = StreamingVRC48M(chunk_size=3)
        stream.process_frame(make_frame())
        stream.finalize()
        with pytest.raises(RuntimeError, match="Cannot process frames"):
            stream.process_frame(make_frame())

    def test_flush_after_finalize_raises(self):
        stream = StreamingVRC48M(chunk_size=3)
        stream.process_frame(make_frame())
        stream.finalize()
        with pytest.raises(RuntimeError, match="Cannot flush"):
            stream.flush()

    def test_dimensions_autodetected(self):
        """Width/height should be inferred from first frame if not provided."""
        stream = StreamingVRC48M(chunk_size=2)
        frame = make_frame(width=320, height=240)
        stream.process_frame(frame)
        stream.process_frame(frame)
        analysis = stream.finalize()
        assert analysis.width == 320
        assert analysis.height == 240

    def test_deterministic(self):
        """Two identical streams should produce identical results."""
        frames = [make_frame(color=(50 + i * 20, 100, 80)) for i in range(4)]

        def run():
            s = StreamingVRC48M(chunk_size=2, fps=24.0)
            for f in frames:
                s.process_frame(f)
            return s.finalize()

        a = run()
        b = run()
        assert a.merkle_root == b.merkle_root
        assert len(a.chunks) == len(b.chunks)
        for ca, cb in zip(a.chunks, b.chunks):
            assert ca.spectrum == cb.spectrum
            assert ca.digest == cb.digest

    def test_single_frame_equivalence_with_analyze_image(self, tmp_path):
        """Streaming a single frame should match analyze_image for the same content."""
        frame = make_gradient_frame(width=128, height=128)
        img_path = str(tmp_path / "equiv.png")
        cv2.imwrite(img_path, frame)

        # analyze_image path
        img_analysis = analyze_image(img_path)

        # Streaming path — read back from disk so pixel values match exactly
        frame_read = cv2.imread(img_path)
        stream = StreamingVRC48M(chunk_size=1)
        stream.process_frame(frame_read)
        stream_analysis = stream.finalize()

        assert img_analysis.chunks[0].spectrum == stream_analysis.chunks[0].spectrum
        assert img_analysis.chunks[0].digest == stream_analysis.chunks[0].digest
        assert img_analysis.merkle_root == stream_analysis.merkle_root

    def test_anchor_from_streaming(self):
        """MediaAnchor.from_analysis should work with streaming output."""
        stream = StreamingVRC48M(chunk_size=3, fps=30.0)
        for i in range(6):
            stream.process_frame(make_frame(color=(60 + i * 15, 90, 110)))
        analysis = stream.finalize()

        anchor = MediaAnchor.from_analysis(analysis)
        assert anchor.standard == "VRC-48M"
        assert len(anchor.chunk_spectra) == 2
        assert len(anchor.chunk_digests) == 2
        assert anchor.video_merkle_root == analysis.merkle_root.hex()
