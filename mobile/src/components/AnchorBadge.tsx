/**
 * AnchorBadge — Compact display of a media anchor with key stats.
 */

import React from "react";
import { StyleSheet, Text, View } from "react-native";
import type { AnchorResult } from "../sdk/types";
import { COLORS } from "../utils/config";

interface AnchorBadgeProps {
  result: AnchorResult;
  compact?: boolean;
}

export function AnchorBadge({ result, compact = false }: AnchorBadgeProps) {
  const { anchor } = result;
  const root = anchor.videoMerkleRoot;
  const shortRoot = root.length > 16 ? `${root.slice(0, 8)}...${root.slice(-8)}` : root;

  if (compact) {
    return (
      <View style={styles.compactContainer}>
        <Text style={styles.compactLabel}>VRC-48M</Text>
        <Text style={styles.compactRoot}>{shortRoot}</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.badge}>VRC-48M ANCHOR</Text>
        <Text style={styles.mode}>
          {anchor.captureMode === "live_stream" ? "LIVE" : "FILE"}
        </Text>
      </View>

      <View style={styles.statsGrid}>
        <StatItem label="Frames" value={String(anchor.frameCount)} />
        <StatItem label="Chunks" value={String(result.totalChunks)} />
        <StatItem
          label="Duration"
          value={`${(anchor.durationMs / 1000).toFixed(1)}s`}
        />
        <StatItem
          label="Resolution"
          value={`${anchor.width}x${anchor.height}`}
        />
      </View>

      <View style={styles.merkleRow}>
        <Text style={styles.merkleLabel}>Merkle Root</Text>
        <Text style={styles.merkleValue} numberOfLines={1}>
          {anchor.videoMerkleRoot}
        </Text>
      </View>

      <Text style={styles.processingTime}>
        Processed in {result.processingTimeMs.toFixed(0)}ms
      </Text>
    </View>
  );
}

function StatItem({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.accent,
    borderRadius: 16,
    padding: 20,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 16,
  },
  badge: {
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.5,
    color: COLORS.accent,
  },
  mode: {
    fontSize: 10,
    fontWeight: "700",
    color: COLORS.green,
    backgroundColor: "rgba(34, 255, 136, 0.1)",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: "hidden",
  },
  statsGrid: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 16,
  },
  stat: {
    flex: 1,
    backgroundColor: COLORS.bg,
    borderRadius: 8,
    padding: 10,
    alignItems: "center",
  },
  statValue: {
    fontSize: 18,
    fontWeight: "700",
    color: COLORS.accent,
    fontVariant: ["tabular-nums"],
  },
  statLabel: {
    fontSize: 9,
    color: COLORS.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginTop: 2,
  },
  merkleRow: {
    backgroundColor: COLORS.bg,
    borderRadius: 8,
    padding: 10,
    marginBottom: 8,
  },
  merkleLabel: {
    fontSize: 9,
    color: COLORS.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  merkleValue: {
    fontSize: 11,
    color: COLORS.accent,
    fontFamily: "monospace",
  },
  processingTime: {
    fontSize: 11,
    color: COLORS.muted,
    textAlign: "right",
  },
  // Compact
  compactContainer: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  compactLabel: {
    fontSize: 10,
    fontWeight: "700",
    color: COLORS.accent,
    letterSpacing: 1,
  },
  compactRoot: {
    fontSize: 10,
    color: COLORS.muted,
    fontFamily: "monospace",
  },
});
