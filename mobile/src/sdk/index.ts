/**
 * VRC-48M Mobile SDK
 *
 * Client library for real-time media anchoring via the VortexChain
 * WebSocket streaming protocol. Framework-agnostic — depends only
 * on socket.io-client.
 *
 * @example
 * ```typescript
 * import { VRC48MClient } from './sdk';
 *
 * const client = new VRC48MClient({
 *   serverUrl: 'http://192.168.1.30:5000',
 * });
 *
 * await client.connect();
 * await client.startSession();
 *
 * client.on('chunk', (chunk) => {
 *   console.log(`Chunk ${chunk.chunkIndex} anchored`);
 * });
 *
 * // In your camera frame callback:
 * client.sendFrame(jpegArrayBuffer);
 *
 * // When recording stops:
 * const result = await client.finalize();
 * console.log('Anchor:', result.anchor.videoMerkleRoot);
 * ```
 */

export { VRC48MClient } from "./VRC48MClient";
export { encodeFrame, decodeFrameHeader } from "./frameEncoder";
export {
  saveAnchor,
  loadAnchors,
  getAnchor,
  deleteAnchor,
  clearAnchors,
  exportAnchorJSON,
} from "./sessionStore";
export type {
  VRC48MConfig,
  VRC48MEvents,
  VRC48MError,
  SessionState,
  SessionConfig,
  ChunkResult,
  AnchorResult,
  MediaAnchor,
  VerifyResult,
  TamperedChunk,
  StoredAnchor,
} from "./types";
