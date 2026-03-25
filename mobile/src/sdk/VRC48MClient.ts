/**
 * VRC-48M Streaming Client
 *
 * Core client class that manages the WebSocket connection to the
 * VortexChain server for real-time media anchoring. Designed to be
 * framework-agnostic — works with React Native, web, or Node.js.
 *
 * Usage:
 *   const client = new VRC48MClient({ serverUrl: 'http://192.168.1.30:5000' });
 *   await client.connect();
 *   await client.startSession();
 *   // In camera frame callback:
 *   client.sendFrame(jpegArrayBuffer);
 *   // When done:
 *   const anchor = await client.finalize();
 */

import { io, Socket } from "socket.io-client";
import { encodeFrame } from "./frameEncoder";
import type {
  AnchorResult,
  ChunkResult,
  SessionConfig,
  SessionState,
  VRC48MConfig,
  VRC48MError,
  VRC48MEvents,
} from "./types";

type EventHandler<K extends keyof VRC48MEvents> = VRC48MEvents[K];

const DEFAULT_CONFIG: Required<
  Omit<VRC48MConfig, "serverUrl">
> = {
  fps: 30,
  width: 1280,
  height: 720,
  chunkSize: 10,
  frameSkip: 3,
  jpegQuality: 0.65,
};

export class VRC48MClient {
  private socket: Socket | null = null;
  private sessionId: string | null = null;
  private serverConfig: SessionConfig | null = null;
  private state: SessionState = "idle";
  private frameSequence: number = 0;
  private chunkCount: number = 0;
  private listeners: Map<string, Set<Function>> = new Map();
  private config: Required<VRC48MConfig>;

  // Frame buffer for network resilience
  private frameBuffer: ArrayBuffer[] = [];
  private maxBufferSize = 100; // ~10 seconds at 10fps
  private isConnected = false;

  constructor(config: VRC48MConfig) {
    this.config = { ...DEFAULT_CONFIG, ...config } as Required<VRC48MConfig>;
  }

  // ---------------------------------------------------------------------------
  // Event Emitter
  // ---------------------------------------------------------------------------

  on<K extends keyof VRC48MEvents>(event: K, handler: EventHandler<K>): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler);
  }

  off<K extends keyof VRC48MEvents>(event: K, handler: EventHandler<K>): void {
    this.listeners.get(event)?.delete(handler);
  }

  private emit<K extends keyof VRC48MEvents>(
    event: K,
    ...args: Parameters<VRC48MEvents[K]>
  ): void {
    this.listeners.get(event)?.forEach((handler) => {
      try {
        (handler as Function)(...args);
      } catch (e) {
        console.error(`[VRC48M] Error in ${event} handler:`, e);
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Connection
  // ---------------------------------------------------------------------------

  async connect(): Promise<void> {
    if (this.socket?.connected) return;

    this.setState("connecting");

    return new Promise((resolve, reject) => {
      this.socket = io(this.config.serverUrl, {
        transports: ["websocket"],
        reconnection: true,
        reconnectionAttempts: 10,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 10000,
      });

      this.socket.on("connect", () => {
        this.isConnected = true;
        this.emit("connectionChange", true);
        this.setState("ready");
        this.drainBuffer();
        resolve();
      });

      this.socket.on("disconnect", () => {
        this.isConnected = false;
        this.emit("connectionChange", false);
      });

      this.socket.on("connect_error", (err) => {
        this.isConnected = false;
        this.emit("connectionChange", false);
        if (this.state === "connecting") {
          reject(new Error(`Connection failed: ${err.message}`));
        }
      });

      // VRC-48M protocol events
      this.socket.on("vrc48m:session_created", (data: any) => {
        this.sessionId = data.session_id;
        this.serverConfig = {
          fps: data.config.fps,
          width: data.config.width,
          height: data.config.height,
          chunkSize: data.config.chunk_size,
          frameSkip: data.config.frame_skip,
          sourceFps: data.config.source_fps,
          analysisFps: data.config.analysis_fps,
        };
      });

      this.socket.on("vrc48m:chunk_complete", (data: any) => {
        this.chunkCount++;
        const chunk: ChunkResult = {
          sessionId: data.session_id,
          chunkIndex: data.chunk_index,
          frameStart: data.frame_start,
          frameEnd: data.frame_end,
          spectrum: data.spectrum,
          digestHex: data.digest_hex,
        };
        this.emit("chunk", chunk);
      });

      this.socket.on("vrc48m:anchor_complete", (data: any) => {
        const result: AnchorResult = {
          sessionId: data.session_id,
          anchorId: data.anchor_id,
          anchor: {
            version: data.anchor.version,
            standard: data.anchor.standard,
            filePath: data.anchor.file_path,
            frameCount: data.anchor.frame_count,
            fps: data.anchor.fps,
            width: data.anchor.width,
            height: data.anchor.height,
            durationMs: data.anchor.duration_ms,
            chunkSize: data.anchor.chunk_size,
            videoMerkleRoot: data.anchor.video_merkle_root,
            chunkSpectra: data.anchor.chunk_spectra,
            chunkDigests: data.anchor.chunk_digests,
            sampleSpectra: data.anchor.sample_spectra,
            timestamp: data.anchor.timestamp,
            processingTimeMs: data.anchor.processing_time_ms,
            sourceFps: data.anchor.source_fps,
            analysisFps: data.anchor.analysis_fps,
            frameSkip: data.anchor.frame_skip,
            captureMode: data.anchor.capture_mode,
          },
          totalFrames: data.total_frames,
          totalChunks: data.total_chunks,
          processingTimeMs: data.processing_time_ms,
        };
        this.emit("anchor", result);
      });

      this.socket.on("vrc48m:frame_ack", (data: any) => {
        this.emit("frameAck", data.frame_index);
      });

      this.socket.on("vrc48m:error", (data: any) => {
        const error: VRC48MError = {
          code: data.code,
          message: data.message,
          sessionId: data.session_id,
        };
        this.emit("error", error);
        if (
          data.code !== "DECODE_FAILED" &&
          data.code !== "ABORTED"
        ) {
          this.setState("error");
        }
      });
    });
  }

  disconnect(): void {
    this.socket?.disconnect();
    this.socket = null;
    this.isConnected = false;
    this.setState("idle");
    this.emit("connectionChange", false);
  }

  // ---------------------------------------------------------------------------
  // Recording
  // ---------------------------------------------------------------------------

  async startSession(): Promise<string> {
    if (!this.socket?.connected) {
      throw new Error("Not connected");
    }

    this.frameSequence = 0;
    this.chunkCount = 0;
    this.frameBuffer = [];

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error("Session init timed out"));
      }, 10000);

      const onCreated = (data: any) => {
        clearTimeout(timeout);
        this.sessionId = data.session_id;
        this.setState("recording");
        resolve(data.session_id);
      };

      // Listen for the session_created response
      this.socket!.once("vrc48m:session_created", onCreated);

      this.socket!.emit("vrc48m:init", {
        fps: this.config.fps,
        width: this.config.width,
        height: this.config.height,
        chunk_size: this.config.chunkSize,
        frame_skip: this.config.frameSkip,
        source_fps: this.config.fps,
      });
    });
  }

  /**
   * Send a JPEG frame to the server.
   * If disconnected, buffers the frame for later delivery.
   */
  sendFrame(jpegData: ArrayBuffer): void {
    if (this.state !== "recording" || !this.sessionId) {
      return;
    }

    const encoded = encodeFrame(
      this.sessionId,
      this.frameSequence++,
      jpegData
    );

    if (this.isConnected && this.socket?.connected) {
      this.socket.emit("vrc48m:frame", encoded);
    } else {
      // Buffer for later
      this.bufferFrame(encoded);
    }
  }

  async finalize(): Promise<AnchorResult> {
    if (this.state !== "recording" || !this.sessionId) {
      throw new Error(`Cannot finalize in state ${this.state}`);
    }

    this.setState("finalizing");

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.setState("error");
        reject(new Error("Finalize timed out"));
      }, 30000);

      const onAnchor = (result: AnchorResult) => {
        clearTimeout(timeout);
        this.setState("done");
        resolve(result);
      };

      this.once("anchor", onAnchor);

      this.socket!.emit("vrc48m:finalize", {
        session_id: this.sessionId,
      });
    });
  }

  abort(): void {
    if (this.sessionId && this.socket?.connected) {
      this.socket.emit("vrc48m:abort", {
        session_id: this.sessionId,
      });
    }
    this.setState("idle");
    this.sessionId = null;
    this.frameBuffer = [];
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  getState(): SessionState {
    return this.state;
  }

  getSessionId(): string | null {
    return this.sessionId;
  }

  getChunkCount(): number {
    return this.chunkCount;
  }

  getFrameCount(): number {
    return this.frameSequence;
  }

  getIsConnected(): boolean {
    return this.isConnected;
  }

  getServerConfig(): SessionConfig | null {
    return this.serverConfig;
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private setState(state: SessionState): void {
    if (this.state !== state) {
      this.state = state;
      this.emit("stateChange", state);
    }
  }

  private bufferFrame(encoded: ArrayBuffer): void {
    if (this.frameBuffer.length >= this.maxBufferSize) {
      this.frameBuffer.shift(); // drop oldest
    }
    this.frameBuffer.push(encoded);
  }

  private drainBuffer(): void {
    if (this.frameBuffer.length === 0 || !this.socket?.connected) return;

    const frames = [...this.frameBuffer];
    this.frameBuffer = [];

    for (const frame of frames) {
      this.socket.emit("vrc48m:frame", frame);
    }
  }

  private once<K extends keyof VRC48MEvents>(
    event: K,
    handler: EventHandler<K>
  ): void {
    const wrapped = ((...args: any[]) => {
      this.off(event, wrapped as EventHandler<K>);
      (handler as Function)(...args);
    }) as EventHandler<K>;
    this.on(event, wrapped);
  }
}
