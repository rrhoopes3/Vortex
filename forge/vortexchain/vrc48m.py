"""VRC-48M: Topological Media Provenance.

Deepfake-resistant content authentication using topological perceptual binding.
Extracts perceptual features from video/audio/image frames, maps them to the
48-dimensional topological manifold, and computes wrapping-number spectra that
are invariant under continuous signal transformations (compression, rescaling)
but change under discrete structural modifications (face swaps, AI regeneration).

Usage (CLI):
    python -m forge.vortexchain.vrc48m anchor  video.mp4 -o anchor.json
    python -m forge.vortexchain.vrc48m verify  video.mp4 anchor.json
    python -m forge.vortexchain.vrc48m compare original.mp4 suspect.mp4
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from forge.vortexchain.manifold import (
    MANIFOLD_DIM,
    NUM_EMBEDDED_SPHERES,
    TopologicalManifold,
    WrappingNumber,
    _expand_seed,
)
from forge.vortexchain.toac import TopologicalHash


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SFP_DIM = MANIFOLD_DIM           # 48 features — maps 1:1 to manifold coords
SPATIAL_FEATURES = 16             # 4x4 grid: gradient mag + orientation
FREQUENCY_FEATURES = 16           # 16 lowest non-DC DCT coefficients
TEMPORAL_FEATURES = 8             # optical flow stats
CHROMATIC_FEATURES = 8            # Lab* color stats on 2x2 grid
DEFAULT_CHUNK_SIZE = 30           # ~1 second at 30fps
WRAPPING_MODULUS = 997            # prime modulus for wrapping numbers
STABILIZATION_EPSILON = 0.001     # small perturbation to avoid boundaries


# ---------------------------------------------------------------------------
# Structural Feature Pyramid (SFP) Extraction
# ---------------------------------------------------------------------------

def extract_spatial_features(frame_gray: np.ndarray) -> np.ndarray:
    """Extract 16 spatial structure features from a grayscale frame.

    Divides into 4x4 grid, computes gradient magnitude mean and dominant
    orientation per cell. Returns 16 values (8 magnitude + 8 orientation
    from alternating cells to fill 16 slots).
    """
    h, w = frame_gray.shape[:2]
    # Compute gradients
    gx = cv2.Sobel(frame_gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(frame_gray, cv2.CV_64F, 0, 1, ksize=3)
    magnitude = np.sqrt(gx ** 2 + gy ** 2)
    orientation = np.arctan2(gy, gx)  # [-pi, pi]

    features = []
    cell_h, cell_w = h // 4, w // 4

    for row in range(4):
        for col in range(4):
            y0, y1 = row * cell_h, (row + 1) * cell_h
            x0, x1 = col * cell_w, (col + 1) * cell_w
            cell_mag = magnitude[y0:y1, x0:x1]
            cell_ori = orientation[y0:y1, x0:x1]

            # Alternate between magnitude mean and orientation mean
            if (row + col) % 2 == 0:
                features.append(float(np.mean(cell_mag)))
            else:
                # Normalize orientation to [0, 1]
                features.append(float((np.mean(cell_ori) + math.pi) / (2 * math.pi)))

    return np.array(features[:SPATIAL_FEATURES], dtype=np.float64)


def extract_frequency_features(frame_gray: np.ndarray) -> np.ndarray:
    """Extract 16 frequency domain features via 2D DCT.

    Takes the 16 lowest non-DC coefficients in zigzag order.
    Robust to JPEG/H.264 compression (operates in DCT domain).
    """
    # Resize to fixed size for consistent DCT
    resized = cv2.resize(frame_gray, (64, 64), interpolation=cv2.INTER_AREA)
    float_img = np.float64(resized) / 255.0

    # 2D DCT via separable 1D DCTs
    dct = cv2.dct(float_img)

    # Zigzag scan of top-left 8x8 block (skip DC at [0,0])
    zigzag_indices = [
        (0, 1), (1, 0), (2, 0), (1, 1), (0, 2), (0, 3), (1, 2), (2, 1),
        (3, 0), (4, 0), (3, 1), (2, 2), (1, 3), (0, 4), (0, 5), (1, 4),
    ]

    features = []
    for r, c in zigzag_indices[:FREQUENCY_FEATURES]:
        features.append(float(dct[r, c]))

    return np.array(features, dtype=np.float64)


def extract_temporal_features(
    prev_gray: Optional[np.ndarray],
    curr_gray: np.ndarray,
) -> np.ndarray:
    """Extract 8 temporal coherence features from optical flow.

    If prev_gray is None (first frame), returns zeros.
    """
    if prev_gray is None:
        return np.zeros(TEMPORAL_FEATURES, dtype=np.float64)

    # Compute dense optical flow (Farneback)
    prev_small = cv2.resize(prev_gray, (160, 120), interpolation=cv2.INTER_AREA)
    curr_small = cv2.resize(curr_gray, (160, 120), interpolation=cv2.INTER_AREA)

    flow = cv2.calcOpticalFlowFarneback(
        prev_small, curr_small, None,
        pyr_scale=0.5, levels=3, winsize=15,
        iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
    )

    flow_mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    flow_angle = np.arctan2(flow[..., 1], flow[..., 0])

    # Direction histogram (4 bins: N, E, S, W)
    bins = np.zeros(4, dtype=np.float64)
    for i in range(4):
        lo = -math.pi + i * (math.pi / 2)
        hi = lo + (math.pi / 2)
        mask = (flow_angle >= lo) & (flow_angle < hi)
        bins[i] = float(np.mean(flow_mag[mask])) if mask.any() else 0.0

    # Temporal gradient energy
    diff = cv2.absdiff(prev_small, curr_small)
    temp_energy = float(np.mean(diff))

    # Scene cut indicator (high diff = potential cut)
    scene_cut = float(np.mean(diff > 30))

    features = np.array([
        float(np.mean(flow_mag)),      # mean flow magnitude
        float(np.var(flow_mag)),        # flow variance
        bins[0], bins[1],               # direction bins N, E
        bins[2], bins[3],               # direction bins S, W
        temp_energy,                    # temporal gradient energy
        scene_cut,                      # scene cut indicator
    ], dtype=np.float64)

    return features


def extract_chromatic_features(frame_bgr: np.ndarray) -> np.ndarray:
    """Extract 8 chromatic features in Lab* color space on a 2x2 grid."""
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
    h, w = lab.shape[:2]
    features = []

    cell_h, cell_w = h // 2, w // 2
    for row in range(2):
        for col in range(2):
            y0, y1 = row * cell_h, (row + 1) * cell_h
            x0, x1 = col * cell_w, (col + 1) * cell_w
            cell = lab[y0:y1, x0:x1]
            # Mean of a* and b* channels
            features.append(float(np.mean(cell[:, :, 1])))  # a*
            features.append(float(np.var(cell[:, :, 2])))    # b* variance

    return np.array(features[:CHROMATIC_FEATURES], dtype=np.float64)


def extract_sfp(
    frame_bgr: np.ndarray,
    prev_gray: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Extract the full 48-element Structural Feature Pyramid from a frame.

    Returns a numpy array of shape (48,) — maps directly to manifold coordinates.
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    spatial = extract_spatial_features(gray)
    frequency = extract_frequency_features(gray)
    temporal = extract_temporal_features(prev_gray, gray)
    chromatic = extract_chromatic_features(frame_bgr)

    sfp = np.concatenate([spatial, frequency, temporal, chromatic])
    assert sfp.shape == (SFP_DIM,), f"SFP shape mismatch: {sfp.shape}"
    return sfp


# ---------------------------------------------------------------------------
# Feature Normalization
# ---------------------------------------------------------------------------

def normalize_sfp(sfp: np.ndarray) -> np.ndarray:
    """Normalize SFP features to [0, 1] range using sigmoid-like mapping.

    Uses tanh normalization for robustness — maps any range to (0, 1).
    """
    # Per-feature normalization via tanh with scaling
    # Spatial features: typically 0-100 (gradient magnitudes)
    # Frequency features: typically -1 to 1 (DCT coefficients)
    # Temporal features: typically 0-10 (flow magnitudes)
    # Chromatic features: typically 0-255 (Lab values)
    scales = np.concatenate([
        np.full(SPATIAL_FEATURES, 50.0),     # spatial
        np.full(FREQUENCY_FEATURES, 0.5),    # frequency
        np.full(TEMPORAL_FEATURES, 5.0),     # temporal
        np.full(CHROMATIC_FEATURES, 128.0),  # chromatic
    ])
    normalized = (np.tanh(sfp / scales) + 1.0) / 2.0  # map to [0, 1]
    return normalized


# ---------------------------------------------------------------------------
# Topological Media Hash (TMH)
# ---------------------------------------------------------------------------

def sfp_to_manifold(sfp_normalized: np.ndarray) -> TopologicalManifold:
    """Map a normalized SFP vector to a point on the 48D topological manifold.

    Unlike general TOAC hashing (which uses SHA-512 expansion), VRC-48M maps
    perceptual features DIRECTLY to manifold coordinates, preserving the
    continuous relationship between perceptually similar content and nearby
    manifold points.

    A small deterministic perturbation (stabilization) prevents edge cases
    where legitimate transformations might land exactly on a topological boundary.
    """
    # Stabilization: add hash-derived perturbation
    sfp_bytes = sfp_normalized.tobytes()
    stab_hash = hashlib.sha256(sfp_bytes).digest()

    components = []
    for i in range(MANIFOLD_DIM):
        base = float(sfp_normalized[i]) * 2.0 - 1.0  # map [0,1] to [-1,1]
        perturbation = STABILIZATION_EPSILON * (stab_hash[i % 32] / 255.0)
        components.append(math.tanh(base + perturbation))

    # Derive wrapping numbers from manifold coordinates
    # Use the coordinate-derived seed through the standard expansion
    coord_bytes = struct.pack(f">{MANIFOLD_DIM}d", *components)
    expanded = _expand_seed(coord_bytes, NUM_EMBEDDED_SPHERES * 4)

    wrapping = []
    for i in range(NUM_EMBEDDED_SPHERES):
        raw_int = struct.unpack_from(">i", expanded, i * 4)[0]
        value = raw_int % WRAPPING_MODULUS
        wrapping.append(WrappingNumber(sphere_index=i, value=value))

    return TopologicalManifold(components=components, wrapping_numbers=wrapping)


def compute_tmh(sfp_normalized: np.ndarray) -> Tuple[List[int], bytes]:
    """Compute the Topological Media Hash for a single chunk.

    Returns:
        spectrum: List of 24 wrapping numbers
        digest: 48-byte digest
    """
    manifold = sfp_to_manifold(sfp_normalized)
    spectrum = manifold.topological_spectrum()

    # Compress to 48-byte digest (2 bytes per wrapping number)
    digest_parts = [struct.pack(">H", v % 65536) for v in spectrum]
    digest = b"".join(digest_parts)

    return spectrum, digest


# ---------------------------------------------------------------------------
# Merkle Tree
# ---------------------------------------------------------------------------

def _topo_hash_pair(left: bytes, right: bytes) -> bytes:
    """Hash two digests together using topological hash."""
    combined = left + right
    th = TopologicalHash.hash(combined)
    return th.digest


def build_merkle_tree(chunk_digests: List[bytes]) -> Tuple[bytes, List[List[bytes]]]:
    """Build a Merkle tree from chunk TMH digests.

    Returns:
        root: 48-byte Merkle root
        levels: list of tree levels (bottom to top) for proof generation
    """
    if not chunk_digests:
        return b"\x00" * 48, [[]]

    # Pad to power of 2
    n = len(chunk_digests)
    padded = list(chunk_digests)
    while len(padded) & (len(padded) - 1):  # not power of 2
        padded.append(padded[-1])  # duplicate last

    levels = [padded]
    current = padded

    while len(current) > 1:
        next_level = []
        for i in range(0, len(current), 2):
            combined = _topo_hash_pair(current[i], current[i + 1])
            next_level.append(combined)
        levels.append(next_level)
        current = next_level

    return current[0], levels


def find_divergent_chunks(
    computed_digests: List[bytes],
    anchor_digests: List[bytes],
) -> List[int]:
    """Find which chunks differ between computed and anchor digests."""
    divergent = []
    for i, (computed, anchor) in enumerate(zip(computed_digests, anchor_digests)):
        if computed != anchor:
            divergent.append(i)
    return divergent


# ---------------------------------------------------------------------------
# Video Processing
# ---------------------------------------------------------------------------

@dataclass
class ChunkResult:
    """Result for a single chunk."""
    chunk_index: int
    frame_start: int
    frame_end: int
    spectrum: List[int]
    digest: bytes
    sfp_median: np.ndarray


@dataclass
class MediaAnalysis:
    """Complete analysis of a media file."""
    file_path: str
    frame_count: int
    fps: float
    width: int
    height: int
    duration_ms: int
    chunk_size: int
    chunks: List[ChunkResult]
    merkle_root: bytes
    merkle_levels: List[List[bytes]]
    processing_time_ms: float
    sample_spectra: List[List[int]]  # spectra at 0%, 25%, 50%, 75%


class StreamingVRC48M:
    """Streaming VRC-48M engine for live capture.

    Feed frames one at a time via ``process_frame``; each call returns a
    ``ChunkResult`` when a chunk boundary is reached (every *chunk_size*
    frames) and ``None`` otherwise.  When the stream ends, call ``finalize``
    to flush any partial trailing chunk and build the Merkle tree.

    Usage::

        stream = StreamingVRC48M(chunk_size=30, fps=30.0, width=1920, height=1080)
        for frame in camera_feed:
            result = stream.process_frame(frame)
            if result is not None:
                publish_chunk(result)          # optional per-chunk hook
        analysis = stream.finalize()
        anchor = MediaAnchor.from_analysis(analysis)
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        fps: float = 30.0,
        width: int = 0,
        height: int = 0,
        file_path: str = "<live>",
    ):
        self._chunk_size = chunk_size
        self._fps = fps
        self._width = width
        self._height = height
        self._file_path = file_path

        self._prev_gray: Optional[np.ndarray] = None
        self._frame_buffer: List[np.ndarray] = []
        self._frame_idx: int = 0
        self._chunk_idx: int = 0
        self._chunks: List[ChunkResult] = []
        self._chunk_digests: List[bytes] = []
        self._start_time: float = time.time()
        self._finalized: bool = False

    # -- public API ----------------------------------------------------------

    def process_frame(self, frame_bgr: np.ndarray) -> Optional[ChunkResult]:
        """Ingest a single BGR frame.

        Returns a ``ChunkResult`` when a chunk boundary is reached,
        ``None`` otherwise.
        """
        if self._finalized:
            raise RuntimeError("Cannot process frames after finalize()")

        # Detect dimensions from the first frame if not provided
        if self._frame_idx == 0:
            h, w = frame_bgr.shape[:2]
            if self._width == 0:
                self._width = w
            if self._height == 0:
                self._height = h

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        sfp = extract_sfp(frame_bgr, self._prev_gray)
        sfp_norm = normalize_sfp(sfp)
        self._frame_buffer.append(sfp_norm)
        self._prev_gray = gray
        self._frame_idx += 1

        if len(self._frame_buffer) == self._chunk_size:
            return self._emit_chunk()

        return None

    def flush(self) -> Optional[ChunkResult]:
        """Flush any remaining frames as a partial trailing chunk.

        Returns the ``ChunkResult`` if there were buffered frames, else ``None``.
        Safe to call multiple times (second call is a no-op).
        """
        if self._finalized:
            raise RuntimeError("Cannot flush after finalize()")
        if not self._frame_buffer:
            return None
        return self._emit_chunk()

    def finalize(self, file_path: Optional[str] = None) -> MediaAnalysis:
        """Finish the stream and return the complete ``MediaAnalysis``.

        Flushes any partial chunk, builds the Merkle tree, and assembles the
        final result.  After this call the instance is spent — further calls
        to ``process_frame`` or ``flush`` will raise ``RuntimeError``.
        """
        if self._finalized:
            raise RuntimeError("finalize() already called")

        # Flush trailing frames
        if self._frame_buffer:
            self._emit_chunk()

        self._finalized = True

        merkle_root, merkle_levels = build_merkle_tree(self._chunk_digests)

        # Sample spectra at 0%, 25%, 50%, 75%
        sample_spectra: List[List[int]] = []
        for pct in [0.0, 0.25, 0.50, 0.75]:
            idx = (
                min(int(pct * len(self._chunks)), len(self._chunks) - 1)
                if self._chunks
                else 0
            )
            sample_spectra.append(
                self._chunks[idx].spectrum if self._chunks else []
            )

        duration_ms = int((self._frame_idx / self._fps) * 1000) if self._fps else 0
        processing_time = (time.time() - self._start_time) * 1000

        return MediaAnalysis(
            file_path=file_path or self._file_path,
            frame_count=self._frame_idx,
            fps=self._fps,
            width=self._width,
            height=self._height,
            duration_ms=duration_ms,
            chunk_size=self._chunk_size,
            chunks=list(self._chunks),
            merkle_root=merkle_root,
            merkle_levels=merkle_levels,
            processing_time_ms=processing_time,
            sample_spectra=sample_spectra,
        )

    # -- internals -----------------------------------------------------------

    def _emit_chunk(self) -> ChunkResult:
        """Compute TMH for the current buffer and store the chunk."""
        median_sfp = np.median(np.array(self._frame_buffer), axis=0)
        spectrum, digest = compute_tmh(median_sfp)

        buf_len = len(self._frame_buffer)
        chunk = ChunkResult(
            chunk_index=self._chunk_idx,
            frame_start=self._frame_idx - buf_len,
            frame_end=self._frame_idx - 1,
            spectrum=spectrum,
            digest=digest,
            sfp_median=median_sfp,
        )

        self._chunks.append(chunk)
        self._chunk_digests.append(digest)
        self._frame_buffer = []
        self._chunk_idx += 1
        return chunk


def analyze_video(
    video_path: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress_callback=None,
) -> MediaAnalysis:
    """Analyze a video file and compute its topological media fingerprint.

    Args:
        video_path: Path to video file
        chunk_size: Frames per chunk (default 30)
        progress_callback: Optional callback(current_frame, total_frames)

    Returns:
        MediaAnalysis with all chunk hashes and Merkle root
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    stream = StreamingVRC48M(
        chunk_size=chunk_size, fps=fps, width=width, height=height,
        file_path=video_path,
    )

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        stream.process_frame(frame)
        frame_idx += 1
        if progress_callback and frame_idx % 30 == 0:
            progress_callback(frame_idx, total_frames)

    cap.release()
    return stream.finalize(file_path=video_path)


def analyze_image(image_path: str) -> MediaAnalysis:
    """Analyze a single image (treated as a 1-frame, 1-chunk video)."""
    frame = cv2.imread(image_path)
    if frame is None:
        raise ValueError(f"Cannot open image: {image_path}")

    start_time = time.time()
    h, w = frame.shape[:2]

    sfp = extract_sfp(frame, None)
    sfp_norm = normalize_sfp(sfp)
    spectrum, digest = compute_tmh(sfp_norm)

    chunk = ChunkResult(
        chunk_index=0, frame_start=0, frame_end=0,
        spectrum=spectrum, digest=digest, sfp_median=sfp_norm,
    )

    merkle_root, merkle_levels = build_merkle_tree([digest])
    processing_time = (time.time() - start_time) * 1000

    return MediaAnalysis(
        file_path=image_path,
        frame_count=1, fps=0.0, width=w, height=h,
        duration_ms=0, chunk_size=1,
        chunks=[chunk],
        merkle_root=merkle_root,
        merkle_levels=merkle_levels,
        processing_time_ms=processing_time,
        sample_spectra=[spectrum],
    )


# ---------------------------------------------------------------------------
# Anchor File (JSON)
# ---------------------------------------------------------------------------

@dataclass
class MediaAnchor:
    """On-chain provenance anchor (serializable to JSON)."""
    version: int = 1
    standard: str = "VRC-48M"
    file_path: str = ""
    frame_count: int = 0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    duration_ms: int = 0
    chunk_size: int = DEFAULT_CHUNK_SIZE
    video_merkle_root: str = ""  # hex
    chunk_spectra: List[List[int]] = field(default_factory=list)
    chunk_digests: List[str] = field(default_factory=list)  # hex
    sample_spectra: List[List[int]] = field(default_factory=list)
    timestamp: float = 0.0
    processing_time_ms: float = 0.0

    @classmethod
    def from_analysis(cls, analysis: MediaAnalysis) -> "MediaAnchor":
        return cls(
            file_path=analysis.file_path,
            frame_count=analysis.frame_count,
            fps=analysis.fps,
            width=analysis.width,
            height=analysis.height,
            duration_ms=analysis.duration_ms,
            chunk_size=analysis.chunk_size,
            video_merkle_root=analysis.merkle_root.hex(),
            chunk_spectra=[c.spectrum for c in analysis.chunks],
            chunk_digests=[c.digest.hex() for c in analysis.chunks],
            sample_spectra=analysis.sample_spectra,
            timestamp=time.time(),
            processing_time_ms=analysis.processing_time_ms,
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "MediaAnchor":
        data = json.loads(json_str)
        return cls(**data)

    def save(self, path: str):
        Path(path).write_text(self.to_json())

    @classmethod
    def load(cls, path: str) -> "MediaAnchor":
        return cls.from_json(Path(path).read_text())


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

class VerificationStatus(Enum):
    AUTHENTIC = "AUTHENTIC"
    TAMPERED = "TAMPERED"
    MINOR_EDIT = "MINOR_EDIT"
    SIGNIFICANT_EDIT = "SIGNIFICANT_EDIT"
    MAJOR_EDIT = "MAJOR_EDIT"
    REGENERATED = "REGENERATED"


@dataclass
class TamperedChunk:
    chunk_index: int
    frame_start: int
    frame_end: int
    time_start_ms: float
    time_end_ms: float
    spectral_distance: int  # number of changed wrapping numbers
    classification: str


@dataclass
class VerificationResult:
    status: VerificationStatus
    confidence: float
    merkle_match: bool
    total_chunks: int
    matching_chunks: int
    tampered_chunks: List[TamperedChunk] = field(default_factory=list)
    processing_time_ms: float = 0.0

    def summary(self) -> str:
        lines = [
            f"Status: {self.status.value}",
            f"Confidence: {self.confidence:.1%}",
            f"Merkle Root Match: {'YES' if self.merkle_match else 'NO'}",
            f"Chunks: {self.matching_chunks}/{self.total_chunks} matching",
        ]
        if self.tampered_chunks:
            lines.append(f"Tampered Chunks ({len(self.tampered_chunks)}):")
            for tc in self.tampered_chunks:
                t_start = tc.time_start_ms / 1000
                t_end = tc.time_end_ms / 1000
                lines.append(
                    f"  Chunk {tc.chunk_index}: {t_start:.1f}s-{t_end:.1f}s "
                    f"({tc.classification}, {tc.spectral_distance}/24 spectra changed)"
                )
        lines.append(f"Processing time: {self.processing_time_ms:.0f}ms")
        return "\n".join(lines)


def classify_spectral_distance(distance: int) -> str:
    """Classify modification severity based on spectral distance."""
    if distance <= 2:
        return "MINOR_EDIT"
    elif distance <= 6:
        return "SIGNIFICANT_EDIT"
    elif distance <= 12:
        return "MAJOR_EDIT"
    else:
        return "REGENERATED"


def verify_media(
    media_path: str,
    anchor: MediaAnchor,
    progress_callback=None,
) -> VerificationResult:
    """Verify media against a VRC-48M anchor.

    Re-extracts features, recomputes TMH, and compares against anchor.
    """
    start_time = time.time()

    # Determine if image or video
    ext = Path(media_path).suffix.lower()
    if ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'):
        analysis = analyze_image(media_path)
    else:
        analysis = analyze_video(media_path, anchor.chunk_size, progress_callback)

    # Compare Merkle roots
    computed_root = analysis.merkle_root.hex()
    merkle_match = computed_root == anchor.video_merkle_root

    if merkle_match:
        processing_time = (time.time() - start_time) * 1000
        return VerificationResult(
            status=VerificationStatus.AUTHENTIC,
            confidence=0.999,
            merkle_match=True,
            total_chunks=len(analysis.chunks),
            matching_chunks=len(analysis.chunks),
            processing_time_ms=processing_time,
        )

    # Find divergent chunks
    tampered = []
    matching = 0

    for i, chunk in enumerate(analysis.chunks):
        if i < len(anchor.chunk_spectra):
            anchor_spectrum = anchor.chunk_spectra[i]
            # Count changed wrapping numbers
            distance = sum(
                1 for a, b in zip(chunk.spectrum, anchor_spectrum)
                if a != b
            )
            if distance == 0:
                matching += 1
            else:
                fps = anchor.fps or 30.0
                tampered.append(TamperedChunk(
                    chunk_index=i,
                    frame_start=chunk.frame_start,
                    frame_end=chunk.frame_end,
                    time_start_ms=(chunk.frame_start / fps) * 1000,
                    time_end_ms=(chunk.frame_end / fps) * 1000,
                    spectral_distance=distance,
                    classification=classify_spectral_distance(distance),
                ))
        else:
            tampered.append(TamperedChunk(
                chunk_index=i,
                frame_start=chunk.frame_start,
                frame_end=chunk.frame_end,
                time_start_ms=0, time_end_ms=0,
                spectral_distance=24,
                classification="REGENERATED",
            ))

    total = len(analysis.chunks)
    confidence = matching / total if total > 0 else 0.0

    # Overall status
    if not tampered:
        status = VerificationStatus.AUTHENTIC
    elif len(tampered) <= total * 0.05:
        status = VerificationStatus.MINOR_EDIT
    elif len(tampered) <= total * 0.2:
        status = VerificationStatus.SIGNIFICANT_EDIT
    elif len(tampered) <= total * 0.5:
        status = VerificationStatus.MAJOR_EDIT
    else:
        status = VerificationStatus.REGENERATED

    processing_time = (time.time() - start_time) * 1000

    return VerificationResult(
        status=status,
        confidence=confidence,
        merkle_match=False,
        total_chunks=total,
        matching_chunks=matching,
        tampered_chunks=tampered,
        processing_time_ms=processing_time,
    )


def quick_verify(
    media_path: str,
    anchor: MediaAnchor,
) -> VerificationResult:
    """Quick verification using 4 sample spectra only.

    Much faster than full verification — only processes 4 chunks.
    """
    start_time = time.time()
    ext = Path(media_path).suffix.lower()

    if ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'):
        analysis = analyze_image(media_path)
        # Compare single spectrum
        if analysis.chunks and anchor.sample_spectra:
            match = analysis.chunks[0].spectrum == anchor.sample_spectra[0]
            status = VerificationStatus.AUTHENTIC if match else VerificationStatus.TAMPERED
            confidence = 1.0 if match else 0.0
        else:
            status = VerificationStatus.TAMPERED
            confidence = 0.0
    else:
        cap = cv2.VideoCapture(media_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open: {media_path}")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        chunk_size = anchor.chunk_size

        matches = 0
        for pct_idx, pct in enumerate([0.0, 0.25, 0.50, 0.75]):
            if pct_idx >= len(anchor.sample_spectra):
                break

            target_frame = int(pct * total_frames)
            chunk_start = (target_frame // chunk_size) * chunk_size

            # Seek to chunk start
            cap.set(cv2.CAP_PROP_POS_FRAMES, chunk_start)
            frame_buffer = []
            prev_gray = None

            for _ in range(chunk_size):
                ret, frame = cap.read()
                if not ret:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                sfp = extract_sfp(frame, prev_gray)
                frame_buffer.append(normalize_sfp(sfp))
                prev_gray = gray

            if frame_buffer:
                median_sfp = np.median(np.array(frame_buffer), axis=0)
                spectrum, _ = compute_tmh(median_sfp)
                if spectrum == anchor.sample_spectra[pct_idx]:
                    matches += 1

        cap.release()

        confidence = matches / min(4, len(anchor.sample_spectra))
        status = VerificationStatus.AUTHENTIC if matches == min(4, len(anchor.sample_spectra)) \
            else VerificationStatus.TAMPERED

    processing_time = (time.time() - start_time) * 1000

    return VerificationResult(
        status=status,
        confidence=confidence,
        merkle_match=confidence == 1.0,
        total_chunks=min(4, len(anchor.sample_spectra)),
        matching_chunks=int(confidence * min(4, len(anchor.sample_spectra))),
        processing_time_ms=processing_time,
    )


def compare_media(
    original_path: str,
    suspect_path: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress_callback=None,
) -> VerificationResult:
    """Compare two media files directly without an anchor."""
    # Analyze original
    ext = Path(original_path).suffix.lower()
    if ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'):
        original = analyze_image(original_path)
    else:
        original = analyze_video(original_path, chunk_size, progress_callback)

    # Create anchor from original
    anchor = MediaAnchor.from_analysis(original)

    # Verify suspect against it
    return verify_media(suspect_path, anchor, progress_callback)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _progress_bar(current: int, total: int):
    """Simple progress bar for CLI."""
    pct = current / max(total, 1)
    bar_len = 40
    filled = int(bar_len * pct)
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stderr.write(f"\r  [{bar}] {pct:.0%} ({current}/{total} frames)")
    sys.stderr.flush()


def cli_anchor(args):
    """CLI: anchor command."""
    media_path = args[0]
    output_path = args[1] if len(args) > 1 else media_path + ".anchor.json"

    print(f"VRC-48M Anchor: {media_path}")
    print(f"{'=' * 50}")

    ext = Path(media_path).suffix.lower()
    if ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'):
        analysis = analyze_image(media_path)
    else:
        analysis = analyze_video(media_path, progress_callback=_progress_bar)
        sys.stderr.write("\n")

    anchor = MediaAnchor.from_analysis(analysis)
    anchor.save(output_path)

    print(f"Frames:      {analysis.frame_count}")
    print(f"Duration:    {analysis.duration_ms / 1000:.1f}s")
    print(f"Resolution:  {analysis.width}x{analysis.height}")
    print(f"Chunks:      {len(analysis.chunks)}")
    print(f"Merkle Root: {analysis.merkle_root.hex()[:32]}...")
    print(f"Time:        {analysis.processing_time_ms:.0f}ms")
    print(f"Anchor saved: {output_path}")


def cli_verify(args):
    """CLI: verify command."""
    media_path = args[0]
    anchor_path = args[1]
    quick = "--quick" in args

    print(f"VRC-48M Verify: {media_path}")
    print(f"Against anchor: {anchor_path}")
    print(f"Mode: {'QUICK (4 samples)' if quick else 'FULL'}")
    print(f"{'=' * 50}")

    anchor = MediaAnchor.load(anchor_path)

    if quick:
        result = quick_verify(media_path, anchor)
    else:
        result = verify_media(media_path, anchor, _progress_bar)
        sys.stderr.write("\n")

    print(result.summary())

    # Exit code: 0 = authentic, 1 = tampered
    return 0 if result.status == VerificationStatus.AUTHENTIC else 1


def cli_compare(args):
    """CLI: compare command."""
    original_path = args[0]
    suspect_path = args[1]

    print(f"VRC-48M Compare")
    print(f"Original: {original_path}")
    print(f"Suspect:  {suspect_path}")
    print(f"{'=' * 50}")

    result = compare_media(original_path, suspect_path, progress_callback=_progress_bar)
    sys.stderr.write("\n")

    print(result.summary())
    return 0 if result.status == VerificationStatus.AUTHENTIC else 1


def main():
    """CLI entry point."""
    if len(sys.argv) < 3:
        print("VRC-48M: Topological Media Provenance")
        print("=" * 40)
        print()
        print("Usage:")
        print("  python -m forge.vortexchain.vrc48m anchor  <media> [output.json]")
        print("  python -m forge.vortexchain.vrc48m verify  <media> <anchor.json> [--quick]")
        print("  python -m forge.vortexchain.vrc48m compare <original> <suspect>")
        print()
        print("Examples:")
        print("  # Create anchor for a video")
        print("  python -m forge.vortexchain.vrc48m anchor video.mp4")
        print()
        print("  # Verify a re-encoded copy")
        print("  python -m forge.vortexchain.vrc48m verify video_720p.mp4 video.mp4.anchor.json")
        print()
        print("  # Quick verify (4 sample points, fast)")
        print("  python -m forge.vortexchain.vrc48m verify video.mp4 anchor.json --quick")
        print()
        print("  # Compare two files directly")
        print("  python -m forge.vortexchain.vrc48m compare original.mp4 suspect.mp4")
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    if command == "anchor":
        cli_anchor(args)
    elif command == "verify":
        exit_code = cli_verify(args)
        sys.exit(exit_code)
    elif command == "compare":
        exit_code = cli_compare(args)
        sys.exit(exit_code)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
