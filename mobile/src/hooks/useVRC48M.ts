/**
 * React hook wrapping VRC48MClient for use in components.
 *
 * Manages client lifecycle, exposes reactive state, and handles
 * cleanup on unmount.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { VRC48MClient } from "../sdk/VRC48MClient";
import type {
  AnchorResult,
  ChunkResult,
  SessionState,
  VRC48MConfig,
} from "../sdk/types";

export interface UseVRC48MReturn {
  state: SessionState;
  connected: boolean;
  chunks: ChunkResult[];
  anchor: AnchorResult | null;
  frameCount: number;
  error: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
  startSession: () => Promise<string>;
  sendFrame: (jpegData: ArrayBuffer) => void;
  finalize: () => Promise<AnchorResult>;
  abort: () => void;
  reset: () => void;
}

export function useVRC48M(config: VRC48MConfig): UseVRC48MReturn {
  const clientRef = useRef<VRC48MClient | null>(null);
  const [state, setState] = useState<SessionState>("idle");
  const [connected, setConnected] = useState(false);
  const [chunks, setChunks] = useState<ChunkResult[]>([]);
  const [anchor, setAnchor] = useState<AnchorResult | null>(null);
  const [frameCount, setFrameCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Initialize client
  useEffect(() => {
    const client = new VRC48MClient(config);
    clientRef.current = client;

    client.on("stateChange", setState);
    client.on("connectionChange", setConnected);
    client.on("chunk", (chunk) => {
      setChunks((prev) => [...prev, chunk]);
    });
    client.on("anchor", setAnchor);
    client.on("frameAck", (idx) => setFrameCount(idx));
    client.on("error", (err) => setError(`${err.code}: ${err.message}`));

    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [config.serverUrl]);

  const connect = useCallback(async () => {
    setError(null);
    await clientRef.current?.connect();
  }, []);

  const disconnect = useCallback(() => {
    clientRef.current?.disconnect();
  }, []);

  const startSession = useCallback(async () => {
    setChunks([]);
    setAnchor(null);
    setFrameCount(0);
    setError(null);
    return clientRef.current!.startSession();
  }, []);

  const sendFrame = useCallback((jpegData: ArrayBuffer) => {
    clientRef.current?.sendFrame(jpegData);
  }, []);

  const finalize = useCallback(async () => {
    return clientRef.current!.finalize();
  }, []);

  const abort = useCallback(() => {
    clientRef.current?.abort();
    setChunks([]);
    setAnchor(null);
  }, []);

  const reset = useCallback(() => {
    setChunks([]);
    setAnchor(null);
    setFrameCount(0);
    setError(null);
    setState("ready");
  }, []);

  return {
    state,
    connected,
    chunks,
    anchor,
    frameCount,
    error,
    connect,
    disconnect,
    startSession,
    sendFrame,
    finalize,
    abort,
    reset,
  };
}
