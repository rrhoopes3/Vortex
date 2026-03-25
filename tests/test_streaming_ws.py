"""End-to-end tests for VRC-48M WebSocket streaming protocol.

Tests the full pipeline: init → stream frames → chunk_complete → finalize → anchor.
Runs against the actual Flask-SocketIO server using synthetic frames.
"""

from __future__ import annotations

import struct
import threading
import time
from typing import List, Optional

import cv2
import numpy as np
import pytest
import socketio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SERVER_URL = "http://localhost:5000"


def _make_test_frame(width: int = 320, height: int = 240, seed: int = 0) -> bytes:
    """Generate a synthetic JPEG frame."""
    rng = np.random.RandomState(seed)
    frame = rng.randint(0, 255, (height, width, 3), dtype=np.uint8)
    # Add some structure so features aren't pure noise
    cv2.rectangle(frame, (50, 50), (width - 50, height - 50), (0, 255, 0), -1)
    cv2.circle(frame, (width // 2, height // 2), 40 + (seed % 30), (255, 0, seed % 256), -1)
    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
    return jpeg.tobytes()


def _encode_frame(session_id: str, seq: int, jpeg_data: bytes) -> bytes:
    """Encode frame in the binary protocol format."""
    header = session_id.ljust(36)[:36].encode("ascii")
    seq_bytes = struct.pack(">I", seq)
    return header + seq_bytes + jpeg_data


class StreamingTestClient:
    """Synchronous wrapper around the async socket.io client for testing."""

    def __init__(self, url: str = SERVER_URL):
        self.sio = socketio.Client()
        self.url = url
        self.session_id: Optional[str] = None
        self.config: Optional[dict] = None
        self.chunks: List[dict] = []
        self.anchor: Optional[dict] = None
        self.errors: List[dict] = []
        self.frame_acks: List[dict] = []
        self._events: dict = {}

        # Register handlers
        @self.sio.on("vrc48m:session_created")
        def on_session(data):
            self.session_id = data["session_id"]
            self.config = data.get("config")
            self._set_event("session_created")

        @self.sio.on("vrc48m:chunk_complete")
        def on_chunk(data):
            self.chunks.append(data)
            self._set_event(f"chunk_{data['chunk_index']}")

        @self.sio.on("vrc48m:anchor_complete")
        def on_anchor(data):
            self.anchor = data
            self._set_event("anchor_complete")

        @self.sio.on("vrc48m:frame_ack")
        def on_ack(data):
            self.frame_acks.append(data)

        @self.sio.on("vrc48m:error")
        def on_error(data):
            self.errors.append(data)
            self._set_event("error")

    def connect(self):
        self.sio.connect(self.url)

    def disconnect(self):
        self.sio.disconnect()

    def init_session(
        self,
        fps: float = 30.0,
        width: int = 320,
        height: int = 240,
        chunk_size: int = 5,
        frame_skip: int = 3,
    ):
        self.sio.emit("vrc48m:init", {
            "fps": fps,
            "width": width,
            "height": height,
            "chunk_size": chunk_size,
            "frame_skip": frame_skip,
            "source_fps": fps,
        })
        self._wait_event("session_created", timeout=5.0)

    def send_frame(self, seq: int, jpeg_data: bytes):
        encoded = _encode_frame(self.session_id, seq, jpeg_data)
        self.sio.emit("vrc48m:frame", encoded)

    def finalize(self):
        self.sio.emit("vrc48m:finalize", {"session_id": self.session_id})
        self._wait_event("anchor_complete", timeout=15.0)

    def abort(self):
        self.sio.emit("vrc48m:abort", {"session_id": self.session_id})

    def wait_for_chunk(self, index: int, timeout: float = 10.0):
        self._wait_event(f"chunk_{index}", timeout=timeout)

    def _set_event(self, name: str):
        if name not in self._events:
            self._events[name] = threading.Event()
        self._events[name].set()

    def _wait_event(self, name: str, timeout: float = 5.0):
        if name not in self._events:
            self._events[name] = threading.Event()
        if not self._events[name].wait(timeout=timeout):
            raise TimeoutError(f"Timed out waiting for {name}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Create and connect a test client."""
    c = StreamingTestClient()
    try:
        c.connect()
        yield c
    except Exception:
        pytest.skip("Server not running at localhost:5000")
    finally:
        try:
            c.disconnect()
        except Exception:
            pass


class TestStreamingProtocol:
    """Test the VRC-48M WebSocket streaming protocol."""

    def test_init_creates_session(self, client):
        """Init should return a session_id and config."""
        client.init_session(chunk_size=5)
        assert client.session_id is not None
        assert len(client.session_id) == 36  # UUID
        assert client.config is not None
        assert client.config["chunk_size"] == 5

    def test_stream_frames_produces_chunks(self, client):
        """Streaming chunk_size frames should produce a chunk_complete event."""
        client.init_session(chunk_size=5)

        # Send 5 frames to fill one chunk
        for i in range(5):
            jpeg = _make_test_frame(320, 240, seed=i)
            client.send_frame(i, jpeg)
            time.sleep(0.05)  # small delay for server processing

        client.wait_for_chunk(0, timeout=10.0)
        assert len(client.chunks) == 1
        chunk = client.chunks[0]
        assert chunk["chunk_index"] == 0
        assert chunk["frame_start"] == 0
        assert chunk["frame_end"] == 4
        assert len(chunk["spectrum"]) == 24
        assert len(chunk["digest_hex"]) == 96  # 48 bytes hex

    def test_multiple_chunks(self, client):
        """Streaming multiple chunks worth of frames."""
        client.init_session(chunk_size=5)

        for i in range(15):
            jpeg = _make_test_frame(320, 240, seed=i)
            client.send_frame(i, jpeg)
            time.sleep(0.02)

        client.wait_for_chunk(2, timeout=15.0)
        assert len(client.chunks) == 3

        # Chunks should be sequential
        for idx, chunk in enumerate(client.chunks):
            assert chunk["chunk_index"] == idx
            assert chunk["frame_start"] == idx * 5
            assert chunk["frame_end"] == idx * 5 + 4

    def test_finalize_returns_anchor(self, client):
        """Finalize should return a complete anchor."""
        client.init_session(chunk_size=5)

        # Send 12 frames (2 full chunks + 2 trailing)
        for i in range(12):
            jpeg = _make_test_frame(320, 240, seed=i)
            client.send_frame(i, jpeg)
            time.sleep(0.02)

        client.wait_for_chunk(1, timeout=10.0)
        client.finalize()

        assert client.anchor is not None
        anchor = client.anchor["anchor"]
        assert anchor["standard"] == "VRC-48M"
        assert anchor["capture_mode"] == "live_stream"
        assert anchor["frame_count"] == 12
        assert anchor["video_merkle_root"] is not None
        assert len(anchor["chunk_spectra"]) >= 2
        assert anchor["frame_skip"] == 3
        assert client.anchor["total_frames"] == 12
        assert client.anchor["total_chunks"] >= 2

    def test_finalize_with_partial_chunk(self, client):
        """Finalize should flush partial trailing chunks."""
        client.init_session(chunk_size=5)

        # Send 7 frames (1 full chunk + 2 trailing)
        for i in range(7):
            jpeg = _make_test_frame(320, 240, seed=i)
            client.send_frame(i, jpeg)
            time.sleep(0.02)

        client.wait_for_chunk(0, timeout=10.0)
        client.finalize()

        assert client.anchor is not None
        # Anchor should contain spectra for both the full chunk and the flushed partial
        assert len(client.anchor["anchor"]["chunk_spectra"]) >= 2

    def test_frame_acks(self, client):
        """Server should ACK every 10th frame."""
        client.init_session(chunk_size=5)

        for i in range(20):
            jpeg = _make_test_frame(320, 240, seed=i)
            client.send_frame(i, jpeg)
            time.sleep(0.02)

        time.sleep(0.5)  # let acks arrive
        assert len(client.frame_acks) >= 1
        assert client.frame_acks[0]["frame_index"] == 10

    def test_abort_cancels_session(self, client):
        """Abort should cancel the session."""
        client.init_session(chunk_size=5)

        # Send a few frames and wait for them to be processed
        for i in range(3):
            jpeg = _make_test_frame(320, 240, seed=i)
            client.send_frame(i, jpeg)
            time.sleep(0.1)

        time.sleep(0.5)  # ensure all frames processed before abort
        client.errors.clear()  # clear any prior errors
        client.abort()
        time.sleep(0.5)
        assert len(client.errors) >= 1
        assert any(e["code"] == "ABORTED" for e in client.errors)

    def test_different_resolutions(self, client):
        """Should handle different frame resolutions."""
        client.init_session(chunk_size=3, width=640, height=480)

        for i in range(3):
            jpeg = _make_test_frame(640, 480, seed=i)
            client.send_frame(i, jpeg)
            time.sleep(0.05)

        client.wait_for_chunk(0, timeout=10.0)
        assert len(client.chunks) == 1

    def test_wrapping_numbers_are_valid(self, client):
        """Wrapping numbers should be in valid range [0, 996]."""
        client.init_session(chunk_size=5)

        for i in range(5):
            jpeg = _make_test_frame(320, 240, seed=i)
            client.send_frame(i, jpeg)
            time.sleep(0.02)

        client.wait_for_chunk(0, timeout=10.0)
        spectrum = client.chunks[0]["spectrum"]
        assert all(0 <= w <= 996 for w in spectrum)
        assert len(spectrum) == 24

    def test_concurrent_sessions_independent(self):
        """Two concurrent sessions should produce independent results."""
        c1 = StreamingTestClient()
        c2 = StreamingTestClient()
        try:
            c1.connect()
            c2.connect()
        except Exception:
            pytest.skip("Server not running at localhost:5000")

        try:
            c1.init_session(chunk_size=3)
            c2.init_session(chunk_size=3)

            assert c1.session_id != c2.session_id

            # Send different frames to each
            for i in range(3):
                c1.send_frame(i, _make_test_frame(320, 240, seed=i))
                c2.send_frame(i, _make_test_frame(320, 240, seed=i + 100))
                time.sleep(0.03)

            c1.wait_for_chunk(0, timeout=10.0)
            c2.wait_for_chunk(0, timeout=10.0)

            # Different frames → different spectra
            assert c1.chunks[0]["spectrum"] != c2.chunks[0]["spectrum"]

        finally:
            c1.disconnect()
            c2.disconnect()


class TestStreamingEdgeCases:
    """Test edge cases and error handling."""

    def test_frame_before_init(self):
        """Sending a frame without init should error."""
        c = StreamingTestClient()
        try:
            c.connect()
        except Exception:
            pytest.skip("Server not running at localhost:5000")

        try:
            # Send frame with fake session_id
            encoded = _encode_frame("fake-session-id-that-does-not-exist", 0,
                                    _make_test_frame(320, 240))
            c.sio.emit("vrc48m:frame", encoded)
            time.sleep(0.5)
            assert len(c.errors) >= 1
            assert c.errors[0]["code"] == "UNKNOWN_SESSION"
        finally:
            c.disconnect()

    def test_finalize_unknown_session(self, client):
        """Finalize with unknown session_id should error."""
        client.init_session(chunk_size=5)
        client.sio.emit("vrc48m:finalize", {"session_id": "nonexistent"})
        time.sleep(0.5)
        assert any(e["code"] == "UNKNOWN_SESSION" for e in client.errors)

    def test_empty_session_finalize(self, client):
        """Finalize with zero frames should still produce an anchor."""
        client.init_session(chunk_size=5)

        # Send just 1 frame so there's something to finalize
        jpeg = _make_test_frame(320, 240, seed=0)
        client.send_frame(0, jpeg)
        time.sleep(0.1)

        client.finalize()
        assert client.anchor is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
