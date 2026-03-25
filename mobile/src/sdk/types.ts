/**
 * VRC-48M Mobile SDK — Type Definitions
 *
 * Shared interfaces for the WebSocket streaming protocol between
 * the mobile client and VortexChain server.
 */

// ---------------------------------------------------------------------------
// Session & Config
// ---------------------------------------------------------------------------

export type SessionState =
  | "idle"
  | "connecting"
  | "ready"
  | "recording"
  | "finalizing"
  | "done"
  | "error";

export interface VRC48MConfig {
  /** Server URL (e.g., "http://192.168.1.30:5000") */
  serverUrl: string;
  /** Camera capture FPS (default 30) */
  fps?: number;
  /** Frame width in pixels */
  width?: number;
  /** Frame height in pixels */
  height?: number;
  /** Frames per chunk on server (adjusted for skip, default 10) */
  chunkSize?: number;
  /** Send every Nth frame (default 3 → 10fps at 30fps capture) */
  frameSkip?: number;
  /** JPEG quality 0-1 (default 0.65) */
  jpegQuality?: number;
}

export interface SessionConfig {
  fps: number;
  width: number;
  height: number;
  chunkSize: number;
  frameSkip: number;
  sourceFps: number;
  analysisFps: number;
}

// ---------------------------------------------------------------------------
// Chunk & Anchor
// ---------------------------------------------------------------------------

export interface ChunkResult {
  sessionId: string;
  chunkIndex: number;
  frameStart: number;
  frameEnd: number;
  /** 24 wrapping numbers (0-996 each) */
  spectrum: number[];
  /** 48-byte digest as 96-char hex string */
  digestHex: string;
}

export interface MediaAnchor {
  version: number;
  standard: "VRC-48M";
  filePath: string;
  frameCount: number;
  fps: number;
  width: number;
  height: number;
  durationMs: number;
  chunkSize: number;
  videoMerkleRoot: string;
  chunkSpectra: number[][];
  chunkDigests: string[];
  sampleSpectra: number[][];
  timestamp: number;
  processingTimeMs: number;
  // Streaming-specific
  sourceFps?: number;
  analysisFps?: number;
  frameSkip?: number;
  captureMode?: "live_stream" | "file";
  droppedFrameRanges?: [number, number][];
}

export interface AnchorResult {
  sessionId: string;
  anchorId: string;
  anchor: MediaAnchor;
  totalFrames: number;
  totalChunks: number;
  processingTimeMs: number;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export interface VRC48MError {
  code: string;
  message: string;
  sessionId?: string;
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

export interface VRC48MEvents {
  chunk: (chunk: ChunkResult) => void;
  anchor: (result: AnchorResult) => void;
  error: (error: VRC48MError) => void;
  stateChange: (state: SessionState) => void;
  connectionChange: (connected: boolean) => void;
  frameAck: (frameIndex: number) => void;
}

// ---------------------------------------------------------------------------
// REST API responses (for verify/compare)
// ---------------------------------------------------------------------------

export interface TamperedChunk {
  chunkIndex: number;
  frameStart: number;
  frameEnd: number;
  timeStartS: number;
  timeEndS: number;
  spectralDistance: number;
  classification: string;
}

export interface VerifyResult {
  status: "authentic" | "likely_authentic" | "tampered" | "likely_tampered" | "regenerated";
  confidence: number;
  merkleMatch: boolean;
  totalChunks: number;
  matchingChunks: number;
  tamperedChunks: TamperedChunk[];
  processingTimeMs: number;
}

// ---------------------------------------------------------------------------
// Stored anchor (local persistence)
// ---------------------------------------------------------------------------

export interface StoredAnchor {
  id: string;
  anchor: MediaAnchor;
  createdAt: number;
  thumbnailUri?: string;
  durationS: number;
  chunks: number;
}
