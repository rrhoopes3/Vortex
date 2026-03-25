"""Robustness tests for VRC-48M media provenance engine.

Empirically verifies that topological invariants (wrapping numbers / spectra)
are stable under continuous signal transforms (compression, scaling, brightness)
but break under discrete structural tampering (frame replacement, splicing,
reordering, face insertion, content regeneration).

All tests use synthetic frames generated with numpy/cv2 — no external media
files are required.
"""

from __future__ import annotations

import math
import unittest
from typing import List, Tuple

import cv2
import numpy as np

from vortexchain.vrc48m import (
    extract_sfp,
    normalize_sfp,
    compute_tmh,
    StreamingVRC48M,
    MediaAnchor,
    ChunkResult,
    DEFAULT_CHUNK_SIZE,
    MANIFOLD_DIM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gradient_frame(
    width: int = 640,
    height: int = 480,
    phase: float = 0.0,
) -> np.ndarray:
    """Create a synthetic BGR gradient frame with a moving diagonal pattern.

    ``phase`` in [0, 1) shifts the pattern so successive frames simulate
    smooth motion, which produces nonzero optical-flow features.
    """
    y = np.linspace(0, 1, height, dtype=np.float32)
    x = np.linspace(0, 1, width, dtype=np.float32)
    xv, yv = np.meshgrid(x, y)

    diag = (xv + yv + phase) % 1.0
    b = (diag * 255).astype(np.uint8)
    g = ((1.0 - diag) * 200 + 55).astype(np.uint8)
    r = ((np.sin(diag * 2 * math.pi) * 0.5 + 0.5) * 255).astype(np.uint8)

    return np.stack([b, g, r], axis=-1)


def _make_video_sequence(
    n_frames: int = 30,
    width: int = 640,
    height: int = 480,
) -> List[np.ndarray]:
    """Return a list of BGR frames forming a smooth synthetic video."""
    return [
        _make_gradient_frame(width, height, phase=i / n_frames)
        for i in range(n_frames)
    ]


def _compute_spectrum_for_sequence(frames: List[np.ndarray]) -> List[int]:
    """Compute the TMH spectrum for a frame sequence treated as one chunk.

    Extracts SFP for every frame (with temporal features), takes the median
    normalised SFP, then computes the wrapping-number spectrum.
    """
    sfps: List[np.ndarray] = []
    prev_gray = None
    for frame in frames:
        sfp = extract_sfp(frame, prev_gray)
        sfps.append(normalize_sfp(sfp))
        prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    median_sfp = np.median(np.array(sfps), axis=0)
    spectrum, _ = compute_tmh(median_sfp)
    return spectrum


def spectrum_l1_distance(a: List[int], b: List[int]) -> int:
    """L1 (Manhattan) distance between two wrapping-number spectra."""
    assert len(a) == len(b), f"Spectrum lengths differ: {len(a)} vs {len(b)}"
    return sum(abs(ai - bi) for ai, bi in zip(a, b))


# ---------------------------------------------------------------------------
# Category 1: Continuous Transform Invariance (spectra should be STABLE)
# ---------------------------------------------------------------------------

class TestContinuousTransformInvariance(unittest.TestCase):
    """Transforms that are topologically continuous should NOT change the
    wrapping-number spectrum (or change it only within a tight tolerance)."""

    # Shared across every test in this class — generated once.
    _frames: List[np.ndarray] = []
    _original_spectrum: List[int] = []

    @classmethod
    def setUpClass(cls) -> None:
        cls._frames = _make_video_sequence(30, 640, 480)
        cls._original_spectrum = _compute_spectrum_for_sequence(cls._frames)

    # -- helpers for applying transforms to all frames ----------------------

    def _spectrum_after_transform(self, transform_fn) -> List[int]:
        transformed = [transform_fn(f) for f in self._frames]
        return _compute_spectrum_for_sequence(transformed)

    def _assert_continuous_invariance(self, spectrum: List[int], label: str,
                                      max_distance: int = 50) -> None:
        dist = spectrum_l1_distance(self._original_spectrum, spectrum)
        self.assertLessEqual(
            dist, max_distance,
            f"{label}: L1 distance {dist} exceeds threshold {max_distance}",
        )

    # -- JPEG compression ---------------------------------------------------

    def _jpeg_roundtrip(self, frame: np.ndarray, quality: int) -> np.ndarray:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        assert ok, "JPEG encode failed"
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)

    def test_jpeg_q95(self) -> None:
        sp = self._spectrum_after_transform(lambda f: self._jpeg_roundtrip(f, 95))
        self._assert_continuous_invariance(sp, "JPEG Q95")

    def test_jpeg_q80(self) -> None:
        sp = self._spectrum_after_transform(lambda f: self._jpeg_roundtrip(f, 80))
        self._assert_continuous_invariance(sp, "JPEG Q80")

    def test_jpeg_q60(self) -> None:
        sp = self._spectrum_after_transform(lambda f: self._jpeg_roundtrip(f, 60))
        self._assert_continuous_invariance(sp, "JPEG Q60")

    def test_jpeg_q40(self) -> None:
        sp = self._spectrum_after_transform(lambda f: self._jpeg_roundtrip(f, 40))
        self._assert_continuous_invariance(sp, "JPEG Q40", max_distance=80)

    # -- Resolution scaling -------------------------------------------------

    @staticmethod
    def _scale_roundtrip(frame: np.ndarray, target_h: int) -> np.ndarray:
        h, w = frame.shape[:2]
        scale = target_h / h
        target_w = int(w * scale)
        small = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)

    def test_scale_720p(self) -> None:
        sp = self._spectrum_after_transform(lambda f: self._scale_roundtrip(f, 360))
        self._assert_continuous_invariance(sp, "Scale→720p→back")

    def test_scale_480p(self) -> None:
        sp = self._spectrum_after_transform(lambda f: self._scale_roundtrip(f, 240))
        self._assert_continuous_invariance(sp, "Scale→480p→back")

    # -- Brightness / contrast adjustment -----------------------------------

    @staticmethod
    def _adjust_brightness_contrast(frame: np.ndarray, brightness: float,
                                     contrast: float) -> np.ndarray:
        out = frame.astype(np.float32) * contrast + brightness
        return np.clip(out, 0, 255).astype(np.uint8)

    def test_brightness_plus10(self) -> None:
        sp = self._spectrum_after_transform(
            lambda f: self._adjust_brightness_contrast(f, 25.5, 1.0))
        self._assert_continuous_invariance(sp, "Brightness +10%")

    def test_brightness_minus10(self) -> None:
        sp = self._spectrum_after_transform(
            lambda f: self._adjust_brightness_contrast(f, -25.5, 1.0))
        self._assert_continuous_invariance(sp, "Brightness -10%")

    def test_contrast_plus10(self) -> None:
        sp = self._spectrum_after_transform(
            lambda f: self._adjust_brightness_contrast(f, 0, 1.1))
        self._assert_continuous_invariance(sp, "Contrast +10%")

    def test_contrast_minus10(self) -> None:
        sp = self._spectrum_after_transform(
            lambda f: self._adjust_brightness_contrast(f, 0, 0.9))
        self._assert_continuous_invariance(sp, "Contrast -10%")

    # -- Gaussian blur ------------------------------------------------------

    def test_blur_3x3(self) -> None:
        sp = self._spectrum_after_transform(
            lambda f: cv2.GaussianBlur(f, (3, 3), 0))
        self._assert_continuous_invariance(sp, "Blur 3x3")

    def test_blur_5x5(self) -> None:
        sp = self._spectrum_after_transform(
            lambda f: cv2.GaussianBlur(f, (5, 5), 0))
        self._assert_continuous_invariance(sp, "Blur 5x5")

    # -- Color space round-trip ---------------------------------------------

    @staticmethod
    def _color_roundtrip(frame: np.ndarray) -> np.ndarray:
        yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
        return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)

    def test_color_roundtrip_bgr_yuv_bgr(self) -> None:
        sp = self._spectrum_after_transform(self._color_roundtrip)
        self._assert_continuous_invariance(sp, "BGR→YUV→BGR")

    # -- Bitrate simulation (quantisation) ----------------------------------

    @staticmethod
    def _quantize(frame: np.ndarray, levels: int = 32) -> np.ndarray:
        step = 256 // levels
        return (frame // step * step).astype(np.uint8)

    def test_bitrate_quantize_32(self) -> None:
        sp = self._spectrum_after_transform(lambda f: self._quantize(f, 32))
        self._assert_continuous_invariance(sp, "Quantize 32 levels")

    def test_bitrate_quantize_16(self) -> None:
        sp = self._spectrum_after_transform(lambda f: self._quantize(f, 16))
        self._assert_continuous_invariance(sp, "Quantize 16 levels", max_distance=80)


# ---------------------------------------------------------------------------
# Category 2: Discrete Tampering Detection (spectra should DIVERGE)
# ---------------------------------------------------------------------------

class TestDiscreteTamperingDetection(unittest.TestCase):
    """Discrete structural modifications must produce measurably different
    wrapping-number spectra so that tampering is detected."""

    _frames: List[np.ndarray] = []
    _original_spectrum: List[int] = []

    @classmethod
    def setUpClass(cls) -> None:
        cls._frames = _make_video_sequence(30, 640, 480)
        cls._original_spectrum = _compute_spectrum_for_sequence(cls._frames)

    def _assert_tampered(self, spectrum: List[int], label: str,
                          min_distance: int = 200) -> None:
        dist = spectrum_l1_distance(self._original_spectrum, spectrum)
        self.assertGreaterEqual(
            dist, min_distance,
            f"{label}: L1 distance {dist} below detection threshold {min_distance}",
        )

    # -- Frame replacement --------------------------------------------------

    def test_frame_replacement_random_noise(self) -> None:
        tampered = list(self._frames)
        rng = np.random.RandomState(42)
        for i in range(10, 15):  # swap 5 consecutive frames
            tampered[i] = rng.randint(0, 256, tampered[i].shape, dtype=np.uint8)
        sp = _compute_spectrum_for_sequence(tampered)
        self._assert_tampered(sp, "Frame replacement (random noise)")

    # -- Region manipulation (black patch) ----------------------------------

    def test_region_blackout(self) -> None:
        tampered = list(self._frames)
        for i in range(10, 20):
            frame = tampered[i].copy()
            h, w = frame.shape[:2]
            cy, cx = h // 2, w // 2
            frame[cy - 50:cy + 50, cx - 50:cx + 50] = 0
            tampered[i] = frame
        sp = _compute_spectrum_for_sequence(tampered)
        self._assert_tampered(sp, "Region blackout (100x100 center)")

    # -- Frame reordering ---------------------------------------------------

    def test_frame_reversal(self) -> None:
        tampered = list(self._frames)
        tampered[5:25] = tampered[5:25][::-1]  # reverse a large chunk
        sp = _compute_spectrum_for_sequence(tampered)
        self._assert_tampered(sp, "Frame reversal (20 frames)")

    # -- Synthetic face insertion (bright rectangle overlay) -----------------

    def test_synthetic_face_insertion(self) -> None:
        tampered = list(self._frames)
        for i in range(5, 25):
            frame = tampered[i].copy()
            h, w = frame.shape[:2]
            # Paste a bright coloured rectangle simulating a face swap
            frame[h // 4:3 * h // 4, w // 4:3 * w // 4] = [200, 180, 160]
            tampered[i] = frame
        sp = _compute_spectrum_for_sequence(tampered)
        self._assert_tampered(sp, "Synthetic face insertion")

    # -- Content generation (completely different gradient) ------------------

    def test_content_regeneration(self) -> None:
        # Generate an entirely different pattern (inverted + shifted phase)
        regen = []
        for i in range(30):
            phase = (i / 30.0 + 0.5) % 1.0  # shifted by half
            f = _make_gradient_frame(640, 480, phase)
            f = 255 - f  # invert colours
            regen.append(f)
        sp = _compute_spectrum_for_sequence(regen)
        self._assert_tampered(sp, "Content regeneration (inverted + shifted)")


# ---------------------------------------------------------------------------
# Category 3: Streaming Engine Consistency
# ---------------------------------------------------------------------------

class TestStreamingEngineConsistency(unittest.TestCase):
    """The StreamingVRC48M engine must produce identical results to manual
    per-chunk processing and handle boundary conditions correctly."""

    def _process_streaming(self, frames: List[np.ndarray],
                            chunk_size: int) -> "MediaAnalysis":
        stream = StreamingVRC48M(
            chunk_size=chunk_size, fps=30.0, width=640, height=480,
        )
        for frame in frames:
            stream.process_frame(frame)
        return stream.finalize(file_path="<test>")

    def test_streaming_vs_manual_single_chunk(self) -> None:
        """Single complete chunk: streaming and manual should agree."""
        frames = _make_video_sequence(DEFAULT_CHUNK_SIZE, 640, 480)
        analysis = self._process_streaming(frames, DEFAULT_CHUNK_SIZE)

        manual_spectrum = _compute_spectrum_for_sequence(frames)

        self.assertEqual(len(analysis.chunks), 1)
        self.assertEqual(analysis.chunks[0].spectrum, manual_spectrum)

    def test_streaming_vs_manual_multi_chunk(self) -> None:
        """Two complete chunks: each chunk spectrum matches manual."""
        cs = DEFAULT_CHUNK_SIZE
        frames = _make_video_sequence(cs * 2, 640, 480)
        analysis = self._process_streaming(frames, cs)

        self.assertEqual(len(analysis.chunks), 2)

        manual_0 = _compute_spectrum_for_sequence(frames[:cs])
        manual_1 = _compute_spectrum_for_sequence(frames[cs:])

        self.assertEqual(analysis.chunks[0].spectrum, manual_0)
        self.assertEqual(analysis.chunks[1].spectrum, manual_1)

    def test_chunk_boundaries(self) -> None:
        """Chunk boundaries are emitted at the correct frame indices."""
        cs = 10
        n_frames = 35
        frames = _make_video_sequence(n_frames, 640, 480)
        analysis = self._process_streaming(frames, cs)

        # 35 frames / 10 per chunk = 3 full + 1 partial = 4 chunks
        self.assertEqual(len(analysis.chunks), 4)

        self.assertEqual(analysis.chunks[0].frame_start, 0)
        self.assertEqual(analysis.chunks[0].frame_end, 9)
        self.assertEqual(analysis.chunks[1].frame_start, 10)
        self.assertEqual(analysis.chunks[1].frame_end, 19)
        self.assertEqual(analysis.chunks[2].frame_start, 20)
        self.assertEqual(analysis.chunks[2].frame_end, 29)
        # Partial trailing chunk
        self.assertEqual(analysis.chunks[3].frame_start, 30)
        self.assertEqual(analysis.chunks[3].frame_end, 34)

    def test_partial_final_chunk(self) -> None:
        """A trailing partial chunk is flushed on finalize."""
        cs = 10
        n_frames = 15  # 1 full chunk + 5 leftover
        frames = _make_video_sequence(n_frames, 640, 480)
        analysis = self._process_streaming(frames, cs)

        self.assertEqual(len(analysis.chunks), 2)
        self.assertEqual(analysis.chunks[1].frame_end - analysis.chunks[1].frame_start + 1, 5)

    def test_finalize_produces_valid_anchor(self) -> None:
        """finalize() produces a MediaAnalysis convertible to a valid
        MediaAnchor with the correct frame count."""
        frames = _make_video_sequence(60, 640, 480)
        analysis = self._process_streaming(frames, DEFAULT_CHUNK_SIZE)
        anchor = MediaAnchor.from_analysis(analysis)

        self.assertEqual(anchor.frame_count, 60)
        self.assertEqual(anchor.width, 640)
        self.assertEqual(anchor.height, 480)
        self.assertEqual(anchor.standard, "VRC-48M")
        self.assertTrue(len(anchor.video_merkle_root) > 0)
        self.assertEqual(len(anchor.chunk_spectra), len(analysis.chunks))
        self.assertEqual(len(anchor.chunk_digests), len(analysis.chunks))

    def test_process_frame_after_finalize_raises(self) -> None:
        """Calling process_frame after finalize must raise RuntimeError."""
        frames = _make_video_sequence(5, 640, 480)
        stream = StreamingVRC48M(chunk_size=10)
        for f in frames:
            stream.process_frame(f)
        stream.finalize()

        with self.assertRaises(RuntimeError):
            stream.process_frame(frames[0])

    def test_flush_emits_partial_chunk(self) -> None:
        """Explicit flush() before finalize should produce a chunk."""
        stream = StreamingVRC48M(chunk_size=10)
        frames = _make_video_sequence(7, 640, 480)
        results = []
        for f in frames:
            r = stream.process_frame(f)
            if r is not None:
                results.append(r)

        # No full chunk yet
        self.assertEqual(len(results), 0)

        flushed = stream.flush()
        self.assertIsNotNone(flushed)
        self.assertEqual(flushed.frame_end - flushed.frame_start + 1, 7)

    def test_double_finalize_raises(self) -> None:
        """Calling finalize() twice must raise RuntimeError."""
        stream = StreamingVRC48M(chunk_size=10)
        for f in _make_video_sequence(5, 640, 480):
            stream.process_frame(f)
        stream.finalize()
        with self.assertRaises(RuntimeError):
            stream.finalize()


# ---------------------------------------------------------------------------
# Category 4: Spectrum Distance Metrics
# ---------------------------------------------------------------------------

class TestSpectrumDistanceMetrics(unittest.TestCase):
    """Validate that the L1 spectrum distance metric cleanly separates
    continuous transforms from discrete tampering, confirming the existence
    of a workable detection boundary."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._frames = _make_video_sequence(30, 640, 480)
        cls._original_spectrum = _compute_spectrum_for_sequence(cls._frames)

    def test_identical_distance_is_zero(self) -> None:
        dist = spectrum_l1_distance(self._original_spectrum, self._original_spectrum)
        self.assertEqual(dist, 0)

    def test_continuous_transforms_below_threshold(self) -> None:
        """All common continuous transforms produce distance < 50."""
        threshold = 50
        transforms = {
            "JPEG Q80": lambda f: cv2.imdecode(
                cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])[1],
                cv2.IMREAD_COLOR,
            ),
            "Blur 3x3": lambda f: cv2.GaussianBlur(f, (3, 3), 0),
            "Brightness +10%": lambda f: np.clip(
                f.astype(np.float32) + 25.5, 0, 255
            ).astype(np.uint8),
            "BGR→YUV→BGR": lambda f: cv2.cvtColor(
                cv2.cvtColor(f, cv2.COLOR_BGR2YUV), cv2.COLOR_YUV2BGR
            ),
        }

        for label, tfn in transforms.items():
            transformed = [tfn(f) for f in self._frames]
            sp = _compute_spectrum_for_sequence(transformed)
            dist = spectrum_l1_distance(self._original_spectrum, sp)
            self.assertLess(
                dist, threshold,
                f"{label}: distance {dist} >= threshold {threshold}",
            )

    def test_discrete_tampering_above_threshold(self) -> None:
        """Discrete tampering methods produce distance > 200."""
        threshold = 200

        # 1) Random noise replacement
        noise_frames = list(self._frames)
        rng = np.random.RandomState(99)
        for i in range(10, 15):
            noise_frames[i] = rng.randint(0, 256, noise_frames[i].shape, dtype=np.uint8)
        sp_noise = _compute_spectrum_for_sequence(noise_frames)

        # 2) Content regeneration
        regen_frames = [255 - _make_gradient_frame(640, 480, (i / 30.0 + 0.5) % 1.0)
                        for i in range(30)]
        sp_regen = _compute_spectrum_for_sequence(regen_frames)

        cases = {
            "Random noise replacement": sp_noise,
            "Content regeneration": sp_regen,
        }

        for label, sp in cases.items():
            dist = spectrum_l1_distance(self._original_spectrum, sp)
            self.assertGreater(
                dist, threshold,
                f"{label}: distance {dist} <= threshold {threshold}",
            )

    def test_distance_symmetry(self) -> None:
        """L1 distance must be symmetric: d(a,b) == d(b,a)."""
        rng = np.random.RandomState(7)
        a = list(rng.randint(0, 997, 24))
        b = list(rng.randint(0, 997, 24))
        self.assertEqual(spectrum_l1_distance(a, b), spectrum_l1_distance(b, a))

    def test_distance_triangle_inequality(self) -> None:
        """L1 distance must satisfy the triangle inequality."""
        rng = np.random.RandomState(8)
        a = list(rng.randint(0, 997, 24))
        b = list(rng.randint(0, 997, 24))
        c = list(rng.randint(0, 997, 24))
        dab = spectrum_l1_distance(a, b)
        dbc = spectrum_l1_distance(b, c)
        dac = spectrum_l1_distance(a, c)
        self.assertLessEqual(dac, dab + dbc)


if __name__ == "__main__":
    unittest.main()
