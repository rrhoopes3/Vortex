/**
 * ChunkTimeline — Animated horizontal timeline showing chunk anchoring progress.
 *
 * Each chunk appears as a colored bar:
 * - Green: anchored (chunk_complete received)
 * - Cyan pulse: current chunk being filled
 * - Gray: upcoming / empty
 */

import React from "react";
import { StyleSheet, Text, View } from "react-native";
import type { ChunkResult } from "../sdk/types";
import { COLORS } from "../utils/config";

interface ChunkTimelineProps {
  chunks: ChunkResult[];
  currentFrameInChunk?: number;
  chunkSize: number;
  maxVisible?: number;
}

export function ChunkTimeline({
  chunks,
  currentFrameInChunk = 0,
  chunkSize,
  maxVisible = 20,
}: ChunkTimelineProps) {
  const totalSlots = Math.max(chunks.length + 3, 8);
  const visibleSlots = Math.min(totalSlots, maxVisible);
  const fillPct = chunkSize > 0 ? (currentFrameInChunk / chunkSize) * 100 : 0;

  return (
    <View style={styles.container}>
      <View style={styles.timeline}>
        {Array.from({ length: visibleSlots }, (_, i) => {
          const isAnchored = i < chunks.length;
          const isCurrent = i === chunks.length;

          return (
            <View
              key={i}
              style={[
                styles.chunk,
                isAnchored && styles.chunkAnchored,
                isCurrent && styles.chunkCurrent,
                !isAnchored && !isCurrent && styles.chunkEmpty,
              ]}
            >
              {isCurrent && (
                <View
                  style={[styles.chunkFill, { width: `${fillPct}%` }]}
                />
              )}
            </View>
          );
        })}
      </View>
      <View style={styles.legend}>
        <View style={styles.legendItem}>
          <View style={[styles.legendDot, { backgroundColor: COLORS.green }]} />
          <Text style={styles.legendText}>
            {chunks.length} anchored
          </Text>
        </View>
        {currentFrameInChunk > 0 && (
          <View style={styles.legendItem}>
            <View
              style={[styles.legendDot, { backgroundColor: COLORS.accent }]}
            />
            <Text style={styles.legendText}>
              {currentFrameInChunk}/{chunkSize} frames
            </Text>
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingVertical: 8,
  },
  timeline: {
    flexDirection: "row",
    gap: 2,
    height: 32,
    borderRadius: 6,
    overflow: "hidden",
  },
  chunk: {
    flex: 1,
    borderRadius: 3,
    overflow: "hidden",
    position: "relative",
  },
  chunkAnchored: {
    backgroundColor: COLORS.green,
  },
  chunkCurrent: {
    backgroundColor: "rgba(0, 240, 255, 0.15)",
    borderWidth: 1,
    borderColor: COLORS.accent,
  },
  chunkFill: {
    position: "absolute",
    left: 0,
    top: 0,
    bottom: 0,
    backgroundColor: COLORS.accent,
    opacity: 0.4,
  },
  chunkEmpty: {
    backgroundColor: "rgba(255, 255, 255, 0.05)",
  },
  legend: {
    flexDirection: "row",
    gap: 16,
    marginTop: 6,
  },
  legendItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 2,
  },
  legendText: {
    fontSize: 11,
    color: COLORS.muted,
  },
});
