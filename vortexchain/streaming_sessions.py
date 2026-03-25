"""WebSocket streaming session manager for VRC-48M live capture.

Tracks concurrent StreamingVRC48M instances, their state, and handles
cleanup/timeout. Used by the WebSocket handlers in server.py.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from vortexchain.vrc48m import (
    ChunkResult,
    MediaAnchor,
    MediaAnalysis,
    StreamingVRC48M,
)

logger = logging.getLogger(__name__)


class SessionState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    FINALIZING = "finalizing"
    DONE = "done"
    ERROR = "error"


@dataclass
class SessionConfig:
    """Configuration sent by the client at init."""

    fps: float = 30.0
    width: int = 1280
    height: int = 720
    chunk_size: int = 10  # adjusted for frame skip
    frame_skip: int = 3   # client sends every Nth frame
    source_fps: float = 30.0  # original camera fps

    @property
    def analysis_fps(self) -> float:
        return self.source_fps / self.frame_skip

    def to_dict(self) -> dict:
        return {
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "chunk_size": self.chunk_size,
            "frame_skip": self.frame_skip,
            "source_fps": self.source_fps,
            "analysis_fps": self.analysis_fps,
        }


@dataclass
class StreamingSession:
    """A single VRC-48M streaming session."""

    session_id: str
    socket_id: str  # flask-socketio sid
    config: SessionConfig
    state: SessionState = SessionState.IDLE
    stream: Optional[StreamingVRC48M] = None
    created_at: float = field(default_factory=time.time)
    last_frame_at: float = field(default_factory=time.time)
    frame_count: int = 0
    chunk_results: List[dict] = field(default_factory=list)
    anchor: Optional[dict] = None
    error: Optional[str] = None

    def start(self) -> None:
        """Initialize the StreamingVRC48M engine and begin recording."""
        self.stream = StreamingVRC48M(
            chunk_size=self.config.chunk_size,
            fps=self.config.analysis_fps,
            width=self.config.width,
            height=self.config.height,
            file_path="<live-stream>",
        )
        self.state = SessionState.RECORDING
        logger.info(
            "Session %s started: %dx%d @ %.1ffps (skip=%d, chunk=%d)",
            self.session_id,
            self.config.width,
            self.config.height,
            self.config.analysis_fps,
            self.config.frame_skip,
            self.config.chunk_size,
        )

    def process_frame(self, jpeg_data: bytes) -> Optional[dict]:
        """Decode JPEG and process through StreamingVRC48M.

        Returns chunk result dict if a chunk boundary was reached, else None.
        """
        if self.state != SessionState.RECORDING:
            raise RuntimeError(f"Cannot process frame in state {self.state.value}")

        # Decode JPEG to BGR numpy array
        buf = np.frombuffer(jpeg_data, dtype=np.uint8)
        frame_bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame_bgr is None:
            raise ValueError("Failed to decode JPEG frame")

        self.frame_count += 1
        self.last_frame_at = time.time()

        chunk = self.stream.process_frame(frame_bgr)
        if chunk is not None:
            result = _chunk_to_dict(chunk, self.session_id)
            self.chunk_results.append(result)
            return result
        return None

    def finalize(self) -> dict:
        """Finalize the stream and return the full anchor."""
        if self.state != SessionState.RECORDING:
            raise RuntimeError(f"Cannot finalize in state {self.state.value}")

        self.state = SessionState.FINALIZING

        try:
            analysis = self.stream.finalize()
            anchor = MediaAnchor.from_analysis(analysis)

            # Extend anchor with streaming metadata
            anchor_dict = {
                "version": anchor.version,
                "standard": anchor.standard,
                "file_path": anchor.file_path,
                "frame_count": anchor.frame_count,
                "fps": anchor.fps,
                "width": anchor.width,
                "height": anchor.height,
                "duration_ms": anchor.duration_ms,
                "chunk_size": anchor.chunk_size,
                "video_merkle_root": anchor.video_merkle_root,
                "chunk_spectra": anchor.chunk_spectra,
                "chunk_digests": anchor.chunk_digests,
                "sample_spectra": anchor.sample_spectra,
                "timestamp": anchor.timestamp,
                "processing_time_ms": round(anchor.processing_time_ms, 1),
                # Streaming-specific metadata
                "source_fps": self.config.source_fps,
                "analysis_fps": self.config.analysis_fps,
                "frame_skip": self.config.frame_skip,
                "capture_mode": "live_stream",
            }

            self.anchor = anchor_dict
            self.state = SessionState.DONE

            logger.info(
                "Session %s finalized: %d frames, %d chunks, merkle=%s...",
                self.session_id,
                anchor.frame_count,
                len(anchor.chunk_spectra),
                anchor.video_merkle_root[:24],
            )

            return {
                "session_id": self.session_id,
                "anchor": anchor_dict,
                "total_frames": self.frame_count,
                "total_chunks": len(self.chunk_results),
                "processing_time_ms": round(anchor.processing_time_ms, 1),
            }

        except Exception as e:
            self.state = SessionState.ERROR
            self.error = str(e)
            logger.error("Session %s finalize error: %s", self.session_id, e)
            raise

    def abort(self) -> None:
        """Cancel the session and discard all data."""
        self.state = SessionState.ERROR
        self.error = "Aborted by client"
        self.stream = None
        logger.info("Session %s aborted", self.session_id)


class SessionManager:
    """Manages concurrent streaming sessions with automatic cleanup."""

    IDLE_TIMEOUT_S = 60.0
    MAX_SESSIONS = 20

    def __init__(self) -> None:
        self._sessions: Dict[str, StreamingSession] = {}
        self._socket_to_session: Dict[str, str] = {}  # socket_id -> session_id
        self._lock = threading.Lock()

    def create_session(self, socket_id: str, config: SessionConfig) -> StreamingSession:
        """Create and start a new streaming session."""
        with self._lock:
            # Enforce max sessions
            if len(self._sessions) >= self.MAX_SESSIONS:
                self._reap_stale_locked()
                if len(self._sessions) >= self.MAX_SESSIONS:
                    raise RuntimeError("Too many concurrent sessions")

            session_id = str(uuid.uuid4())
            session = StreamingSession(
                session_id=session_id,
                socket_id=socket_id,
                config=config,
            )
            session.start()
            self._sessions[session_id] = session
            self._socket_to_session[socket_id] = session_id
            return session

    def get_session(self, session_id: str) -> Optional[StreamingSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def get_session_for_socket(self, socket_id: str) -> Optional[StreamingSession]:
        """Get the active session for a given socket."""
        sid = self._socket_to_session.get(socket_id)
        if sid:
            return self._sessions.get(sid)
        return None

    def remove_session(self, session_id: str) -> None:
        """Remove a session."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                self._socket_to_session.pop(session.socket_id, None)

    def cleanup_socket(self, socket_id: str) -> None:
        """Clean up sessions for a disconnected socket."""
        with self._lock:
            session_id = self._socket_to_session.pop(socket_id, None)
            if session_id:
                session = self._sessions.get(session_id)
                if session and session.state == SessionState.RECORDING:
                    session.abort()
                    logger.info(
                        "Session %s aborted due to socket disconnect", session_id
                    )

    def reap_stale(self) -> int:
        """Remove sessions that have been idle too long. Returns count reaped."""
        with self._lock:
            return self._reap_stale_locked()

    def _reap_stale_locked(self) -> int:
        now = time.time()
        stale = [
            sid
            for sid, s in self._sessions.items()
            if (now - s.last_frame_at > self.IDLE_TIMEOUT_S
                and s.state in (SessionState.RECORDING, SessionState.IDLE))
            or (now - s.created_at > 300  # 5 min for DONE/ERROR sessions
                and s.state in (SessionState.DONE, SessionState.ERROR))
        ]
        for sid in stale:
            session = self._sessions.pop(sid, None)
            if session:
                self._socket_to_session.pop(session.socket_id, None)
                if session.state == SessionState.RECORDING:
                    session.abort()
                logger.info("Reaped stale session %s (state=%s)", sid, session.state.value)
        return len(stale)

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def list_sessions(self) -> List[dict]:
        """List all sessions (for debugging)."""
        return [
            {
                "session_id": s.session_id,
                "state": s.state.value,
                "frame_count": s.frame_count,
                "chunks": len(s.chunk_results),
                "created_at": s.created_at,
                "last_frame_at": s.last_frame_at,
            }
            for s in self._sessions.values()
        ]


def _chunk_to_dict(chunk: ChunkResult, session_id: str) -> dict:
    """Convert a ChunkResult to a JSON-serializable dict."""
    return {
        "session_id": session_id,
        "chunk_index": chunk.chunk_index,
        "frame_start": chunk.frame_start,
        "frame_end": chunk.frame_end,
        "spectrum": chunk.spectrum,
        "digest_hex": chunk.digest.hex(),
    }
