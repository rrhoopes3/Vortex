/**
 * App configuration constants.
 */

/** Default server URL — change this to your LAN IP for device testing */
export const DEFAULT_SERVER_URL = "http://192.168.1.30:5000";

/** Camera settings */
export const CAMERA_FPS = 30;
export const CAMERA_WIDTH = 1280;
export const CAMERA_HEIGHT = 720;

/** Streaming settings */
export const FRAME_SKIP = 3; // Send every 3rd frame
export const CHUNK_SIZE = 10; // Frames per chunk (at analysis fps)
export const JPEG_QUALITY = 0.65;

/** UI constants */
export const COLORS = {
  bg: "#050507",
  surface: "#0c0c12",
  border: "#1a1a2e",
  accent: "#00f0ff",
  green: "#22ff88",
  red: "#ff4466",
  purple: "#c026d3",
  text: "#e0e0ff",
  muted: "#8899aa",
} as const;
