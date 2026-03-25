/**
 * VRC-48M Frame Encoder
 *
 * Encodes JPEG frame data into the binary protocol format expected by
 * the VRC-48M WebSocket streaming endpoint.
 *
 * Binary layout per frame:
 *   [36 bytes: session_id ASCII, right-padded with spaces]
 *   [4 bytes:  frame sequence number, uint32 big-endian]
 *   [N bytes:  JPEG data]
 */

/**
 * Encode a JPEG frame for transmission over WebSocket.
 *
 * @param sessionId  - 36-char UUID session identifier
 * @param sequence   - Monotonically increasing frame sequence number
 * @param jpegData   - Raw JPEG bytes from the camera
 * @returns ArrayBuffer ready to send as a binary WebSocket message
 */
export function encodeFrame(
  sessionId: string,
  sequence: number,
  jpegData: ArrayBuffer
): ArrayBuffer {
  const HEADER_SIZE = 40; // 36 (session_id) + 4 (sequence)

  const result = new Uint8Array(HEADER_SIZE + jpegData.byteLength);

  // Write session_id (36 bytes, ASCII, space-padded)
  const paddedId = sessionId.padEnd(36).slice(0, 36);
  for (let i = 0; i < 36; i++) {
    result[i] = paddedId.charCodeAt(i);
  }

  // Write sequence number (4 bytes, big-endian uint32)
  result[36] = (sequence >>> 24) & 0xff;
  result[37] = (sequence >>> 16) & 0xff;
  result[38] = (sequence >>> 8) & 0xff;
  result[39] = sequence & 0xff;

  // Write JPEG data
  result.set(new Uint8Array(jpegData), HEADER_SIZE);

  return result.buffer;
}

/**
 * Decode a frame header (for debugging/logging).
 *
 * @param data - Raw binary frame data
 * @returns Parsed header fields
 */
export function decodeFrameHeader(data: ArrayBuffer): {
  sessionId: string;
  sequence: number;
  jpegSize: number;
} {
  const view = new DataView(data);
  const bytes = new Uint8Array(data);

  const sessionId = String.fromCharCode(...bytes.slice(0, 36)).trim();
  const sequence = view.getUint32(36, false); // big-endian

  return {
    sessionId,
    sequence,
    jpegSize: data.byteLength - 40,
  };
}
