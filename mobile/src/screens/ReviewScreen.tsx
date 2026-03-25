/**
 * ReviewScreen — Displays the completed anchor after recording.
 *
 * Shows stats, chunk timeline, merkle root, and share/export options.
 */

import React from "react";
import {
  Alert,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useRoute } from "@react-navigation/native";
import { AnchorBadge } from "../components/AnchorBadge";
import { ChunkTimeline } from "../components/ChunkTimeline";
import type { AnchorResult, ChunkResult } from "../sdk/types";
import { exportAnchorJSON } from "../sdk/sessionStore";
import { COLORS } from "../utils/config";

export function ReviewScreen() {
  const route = useRoute<any>();
  const result: AnchorResult = route.params?.result;

  if (!result) {
    return (
      <View style={styles.centered}>
        <Text style={styles.emptyText}>No anchor to display</Text>
      </View>
    );
  }

  const { anchor } = result;

  // Build mock chunks for timeline visualization
  const mockChunks: ChunkResult[] = anchor.chunkSpectra.map((spectrum, i) => ({
    sessionId: result.sessionId,
    chunkIndex: i,
    frameStart: i * anchor.chunkSize,
    frameEnd: (i + 1) * anchor.chunkSize - 1,
    spectrum,
    digestHex: anchor.chunkDigests[i] || "",
  }));

  const handleShare = async () => {
    try {
      const stored = {
        id: result.anchorId,
        anchor: result.anchor,
        createdAt: Date.now(),
        durationS: anchor.durationMs / 1000,
        chunks: result.totalChunks,
      };
      const json = exportAnchorJSON(stored);
      await Share.share({
        message: json,
        title: `VRC-48M Anchor — ${result.anchorId}`,
      });
    } catch (err: any) {
      Alert.alert("Share Error", err.message);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerIcon}>&#x2705;</Text>
        <Text style={styles.headerTitle}>Media Anchored</Text>
        <Text style={styles.headerSubtitle}>
          Topological proof created at capture
        </Text>
      </View>

      {/* Anchor badge with full stats */}
      <AnchorBadge result={result} />

      {/* Chunk timeline */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Chunk Integrity</Text>
        <ChunkTimeline
          chunks={mockChunks}
          chunkSize={anchor.chunkSize}
        />
      </View>

      {/* Spectra preview */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Sample Spectra</Text>
        <View style={styles.spectraGrid}>
          {anchor.sampleSpectra.map((spectrum, i) => (
            <View key={i} style={styles.spectraItem}>
              <Text style={styles.spectraLabel}>
                {["0%", "25%", "50%", "75%"][i]}
              </Text>
              <View style={styles.spectraBars}>
                {spectrum.slice(0, 12).map((w, j) => (
                  <View
                    key={j}
                    style={[
                      styles.spectraBar,
                      { height: Math.max(2, (w / 997) * 24) },
                    ]}
                  />
                ))}
              </View>
            </View>
          ))}
        </View>
      </View>

      {/* Actions */}
      <View style={styles.actions}>
        <Pressable style={styles.actionBtn} onPress={handleShare}>
          <Text style={styles.actionBtnText}>Share Anchor</Text>
        </Pressable>
      </View>

      {/* Metadata */}
      <View style={styles.metadata}>
        <MetaRow label="Anchor ID" value={result.anchorId} />
        <MetaRow label="Standard" value={anchor.standard} />
        <MetaRow label="Capture Mode" value={anchor.captureMode || "file"} />
        <MetaRow
          label="Frame Skip"
          value={anchor.frameSkip ? `${anchor.frameSkip}x` : "None"}
        />
        <MetaRow
          label="Analysis FPS"
          value={anchor.analysisFps?.toFixed(1) || String(anchor.fps)}
        />
      </View>
    </ScrollView>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.bg,
  },
  content: {
    padding: 20,
    paddingBottom: 60,
  },
  centered: {
    flex: 1,
    backgroundColor: COLORS.bg,
    justifyContent: "center",
    alignItems: "center",
  },
  emptyText: {
    color: COLORS.muted,
    fontSize: 16,
  },
  header: {
    alignItems: "center",
    marginBottom: 24,
  },
  headerIcon: {
    fontSize: 48,
    marginBottom: 8,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: "700",
    color: COLORS.text,
    marginBottom: 4,
  },
  headerSubtitle: {
    fontSize: 14,
    color: COLORS.muted,
  },
  section: {
    marginTop: 24,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: "700",
    color: COLORS.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
    marginBottom: 12,
  },
  spectraGrid: {
    flexDirection: "row",
    gap: 8,
  },
  spectraItem: {
    flex: 1,
    backgroundColor: COLORS.surface,
    borderRadius: 8,
    padding: 8,
    alignItems: "center",
  },
  spectraLabel: {
    fontSize: 10,
    color: COLORS.muted,
    marginBottom: 6,
  },
  spectraBars: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 1,
    height: 24,
  },
  spectraBar: {
    width: 3,
    backgroundColor: COLORS.accent,
    borderRadius: 1,
    opacity: 0.7,
  },
  actions: {
    flexDirection: "row",
    gap: 12,
    marginTop: 24,
  },
  actionBtn: {
    flex: 1,
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.accent,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  actionBtnText: {
    fontSize: 14,
    fontWeight: "600",
    color: COLORS.accent,
  },
  metadata: {
    marginTop: 24,
    backgroundColor: COLORS.surface,
    borderRadius: 12,
    padding: 16,
  },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: COLORS.border,
  },
  metaLabel: {
    fontSize: 12,
    color: COLORS.muted,
  },
  metaValue: {
    fontSize: 12,
    fontWeight: "600",
    color: COLORS.text,
    fontFamily: "monospace",
    maxWidth: "60%",
  },
});
