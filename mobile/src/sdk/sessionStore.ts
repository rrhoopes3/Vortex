/**
 * VRC-48M Session Store
 *
 * Local persistence for anchors using AsyncStorage.
 * Stores anchors on device so users can review past recordings
 * and verify videos offline against previously created anchors.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import type { AnchorResult, StoredAnchor } from "./types";

const STORE_KEY = "@vrc48m_anchors";
const MAX_STORED = 100;

/**
 * Save an anchor result to local storage.
 */
export async function saveAnchor(
  result: AnchorResult,
  thumbnailUri?: string
): Promise<StoredAnchor> {
  const stored: StoredAnchor = {
    id: result.anchorId,
    anchor: result.anchor,
    createdAt: Date.now(),
    thumbnailUri,
    durationS: result.anchor.durationMs / 1000,
    chunks: result.totalChunks,
  };

  const existing = await loadAnchors();
  existing.unshift(stored);

  // Trim to max
  if (existing.length > MAX_STORED) {
    existing.length = MAX_STORED;
  }

  await AsyncStorage.setItem(STORE_KEY, JSON.stringify(existing));
  return stored;
}

/**
 * Load all stored anchors, most recent first.
 */
export async function loadAnchors(): Promise<StoredAnchor[]> {
  try {
    const raw = await AsyncStorage.getItem(STORE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as StoredAnchor[];
  } catch {
    return [];
  }
}

/**
 * Get a single anchor by ID.
 */
export async function getAnchor(
  id: string
): Promise<StoredAnchor | null> {
  const anchors = await loadAnchors();
  return anchors.find((a) => a.id === id) ?? null;
}

/**
 * Delete an anchor by ID.
 */
export async function deleteAnchor(id: string): Promise<void> {
  const anchors = await loadAnchors();
  const filtered = anchors.filter((a) => a.id !== id);
  await AsyncStorage.setItem(STORE_KEY, JSON.stringify(filtered));
}

/**
 * Clear all stored anchors.
 */
export async function clearAnchors(): Promise<void> {
  await AsyncStorage.removeItem(STORE_KEY);
}

/**
 * Export an anchor as a JSON string (for sharing).
 */
export function exportAnchorJSON(stored: StoredAnchor): string {
  return JSON.stringify(stored.anchor, null, 2);
}
