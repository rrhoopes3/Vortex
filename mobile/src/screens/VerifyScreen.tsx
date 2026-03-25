/**
 * VerifyScreen — Select a video from the library and verify it against
 * an anchor to check for tampering.
 */

import React, { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import type { StoredAnchor, VerifyResult } from "../sdk/types";
import { loadAnchors } from "../sdk/sessionStore";
import { COLORS, DEFAULT_SERVER_URL } from "../utils/config";

export function VerifyScreen() {
  const [anchors, setAnchors] = useState<StoredAnchor[]>([]);
  const [selectedAnchor, setSelectedAnchor] = useState<StoredAnchor | null>(null);
  const [videoUri, setVideoUri] = useState<string | null>(null);
  const [videoName, setVideoName] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [result, setResult] = useState<VerifyResult | null>(null);

  // Load anchors on mount
  React.useEffect(() => {
    loadAnchors().then(setAnchors);
  }, []);

  const pickVideo = useCallback(async () => {
    const pick = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: "videos",
      quality: 1,
    });
    if (!pick.canceled && pick.assets[0]) {
      setVideoUri(pick.assets[0].uri);
      setVideoName(pick.assets[0].fileName || "Selected video");
      setResult(null);
    }
  }, []);

  const handleVerify = useCallback(async () => {
    if (!videoUri || !selectedAnchor) return;

    setVerifying(true);
    setResult(null);

    try {
      const form = new FormData();

      // React Native FormData with file URI
      form.append("file", {
        uri: videoUri,
        type: "video/mp4",
        name: "verify.mp4",
      } as any);
      form.append("anchor_id", selectedAnchor.id);

      const res = await fetch(`${DEFAULT_SERVER_URL}/api/vrc48m/verify`, {
        method: "POST",
        body: form,
      });

      const data = await res.json();
      if (data.ok) {
        setResult({
          status: data.data.status,
          confidence: data.data.confidence,
          merkleMatch: data.data.merkle_match,
          totalChunks: data.data.total_chunks,
          matchingChunks: data.data.matching_chunks,
          tamperedChunks: (data.data.tampered_chunks || []).map((tc: any) => ({
            chunkIndex: tc.chunk_index,
            frameStart: tc.frame_start,
            frameEnd: tc.frame_end,
            timeStartS: tc.time_start_s,
            timeEndS: tc.time_end_s,
            spectralDistance: tc.spectral_distance,
            classification: tc.classification,
          })),
          processingTimeMs: data.data.processing_time_ms,
        });
      } else {
        Alert.alert("Verification Error", data.error);
      }
    } catch (err: any) {
      Alert.alert("Network Error", err.message);
    }

    setVerifying(false);
  }, [videoUri, selectedAnchor]);

  const isAuthentic =
    result?.status === "authentic" || result?.status === "likely_authentic";

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>Verify Media</Text>
      <Text style={styles.subtitle}>
        Check a video against a topological anchor
      </Text>

      {/* Step 1: Select anchor */}
      <View style={styles.section}>
        <Text style={styles.stepLabel}>1. Select anchor</Text>
        {anchors.length === 0 ? (
          <Text style={styles.emptyText}>
            No anchors yet. Record a video first.
          </Text>
        ) : (
          <View style={styles.anchorList}>
            {anchors.map((a) => (
              <Pressable
                key={a.id}
                style={[
                  styles.anchorItem,
                  selectedAnchor?.id === a.id && styles.anchorItemSelected,
                ]}
                onPress={() => {
                  setSelectedAnchor(a);
                  setResult(null);
                }}
              >
                <Text style={styles.anchorItemLabel}>VRC-48M</Text>
                <Text style={styles.anchorItemId}>
                  {a.id.slice(0, 20)}...
                </Text>
                <Text style={styles.anchorItemMeta}>
                  {a.chunks} chunks &middot; {a.durationS.toFixed(1)}s
                </Text>
              </Pressable>
            ))}
          </View>
        )}
      </View>

      {/* Step 2: Pick video */}
      <View style={styles.section}>
        <Text style={styles.stepLabel}>2. Pick video to verify</Text>
        <Pressable style={styles.pickBtn} onPress={pickVideo}>
          <Text style={styles.pickBtnText}>
            {videoName || "Choose from library"}
          </Text>
        </Pressable>
      </View>

      {/* Verify button */}
      <Pressable
        style={[
          styles.verifyBtn,
          (!videoUri || !selectedAnchor || verifying) && styles.verifyBtnDisabled,
        ]}
        onPress={handleVerify}
        disabled={!videoUri || !selectedAnchor || verifying}
      >
        {verifying ? (
          <ActivityIndicator color="#000" />
        ) : (
          <Text style={styles.verifyBtnText}>Verify Against Anchor</Text>
        )}
      </Pressable>

      {/* Result */}
      {result && (
        <View
          style={[
            styles.resultCard,
            isAuthentic ? styles.resultAuthentic : styles.resultTampered,
          ]}
        >
          <Text style={styles.resultIcon}>
            {isAuthentic ? "\u2705" : "\uD83D\uDEA8"}
          </Text>
          <Text
            style={[
              styles.resultTitle,
              { color: isAuthentic ? COLORS.green : COLORS.red },
            ]}
          >
            {isAuthentic ? "Authentic" : "Tampering Detected"}
          </Text>
          <Text style={styles.resultSubtitle}>
            {result.matchingChunks}/{result.totalChunks} chunks match &mdash;{" "}
            {(result.confidence * 100).toFixed(1)}% confidence
          </Text>

          {result.tamperedChunks.length > 0 && (
            <View style={styles.tamperedList}>
              {result.tamperedChunks.map((tc, i) => (
                <View key={i} style={styles.tamperedItem}>
                  <View style={styles.tamperedBadge}>
                    <Text style={styles.tamperedBadgeText}>
                      {tc.classification}
                    </Text>
                  </View>
                  <Text style={styles.tamperedDetail}>
                    Chunk {tc.chunkIndex} &mdash; {tc.timeStartS}s to{" "}
                    {tc.timeEndS}s
                  </Text>
                </View>
              ))}
            </View>
          )}

          <Text style={styles.resultTime}>
            Verified in {result.processingTimeMs.toFixed(0)}ms
          </Text>
        </View>
      )}
    </ScrollView>
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
  title: {
    fontSize: 24,
    fontWeight: "700",
    color: COLORS.text,
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 14,
    color: COLORS.muted,
    marginBottom: 24,
  },
  section: {
    marginBottom: 20,
  },
  stepLabel: {
    fontSize: 13,
    fontWeight: "700",
    color: COLORS.text,
    marginBottom: 10,
  },
  emptyText: {
    fontSize: 13,
    color: COLORS.muted,
    fontStyle: "italic",
  },
  anchorList: {
    gap: 8,
  },
  anchorItem: {
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 10,
    padding: 12,
  },
  anchorItemSelected: {
    borderColor: COLORS.accent,
    backgroundColor: "rgba(0, 240, 255, 0.05)",
  },
  anchorItemLabel: {
    fontSize: 10,
    fontWeight: "700",
    color: COLORS.accent,
    letterSpacing: 1,
    marginBottom: 4,
  },
  anchorItemId: {
    fontSize: 12,
    color: COLORS.text,
    fontFamily: "monospace",
  },
  anchorItemMeta: {
    fontSize: 11,
    color: COLORS.muted,
    marginTop: 4,
  },
  pickBtn: {
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 10,
    padding: 16,
    alignItems: "center",
  },
  pickBtnText: {
    fontSize: 14,
    color: COLORS.text,
  },
  verifyBtn: {
    backgroundColor: COLORS.accent,
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: "center",
    marginBottom: 20,
  },
  verifyBtnDisabled: {
    opacity: 0.3,
  },
  verifyBtnText: {
    fontSize: 15,
    fontWeight: "700",
    color: "#000",
  },
  resultCard: {
    borderRadius: 16,
    padding: 20,
    alignItems: "center",
  },
  resultAuthentic: {
    backgroundColor: "rgba(34, 255, 136, 0.08)",
    borderWidth: 1,
    borderColor: "rgba(34, 255, 136, 0.3)",
  },
  resultTampered: {
    backgroundColor: "rgba(255, 68, 102, 0.08)",
    borderWidth: 1,
    borderColor: "rgba(255, 68, 102, 0.3)",
  },
  resultIcon: {
    fontSize: 40,
    marginBottom: 8,
  },
  resultTitle: {
    fontSize: 20,
    fontWeight: "700",
    marginBottom: 4,
  },
  resultSubtitle: {
    fontSize: 13,
    color: COLORS.muted,
    marginBottom: 12,
  },
  tamperedList: {
    width: "100%",
    gap: 6,
    marginBottom: 12,
  },
  tamperedItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "rgba(255, 68, 102, 0.05)",
    borderRadius: 6,
    padding: 8,
  },
  tamperedBadge: {
    backgroundColor: COLORS.red,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  tamperedBadgeText: {
    fontSize: 9,
    fontWeight: "700",
    color: "#fff",
  },
  tamperedDetail: {
    fontSize: 12,
    color: COLORS.text,
  },
  resultTime: {
    fontSize: 11,
    color: COLORS.muted,
  },
});
