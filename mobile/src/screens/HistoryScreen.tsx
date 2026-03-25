/**
 * HistoryScreen — List of past anchors stored locally on the device.
 */

import React, { useCallback, useState } from "react";
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useFocusEffect, useNavigation } from "@react-navigation/native";
import type { StoredAnchor } from "../sdk/types";
import { deleteAnchor, loadAnchors } from "../sdk/sessionStore";
import { COLORS } from "../utils/config";

export function HistoryScreen() {
  const navigation = useNavigation<any>();
  const [anchors, setAnchors] = useState<StoredAnchor[]>([]);

  // Reload on screen focus
  useFocusEffect(
    useCallback(() => {
      loadAnchors().then(setAnchors);
    }, [])
  );

  const handleDelete = useCallback(async (id: string) => {
    await deleteAnchor(id);
    setAnchors((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const handleView = useCallback(
    (anchor: StoredAnchor) => {
      navigation.navigate("Review", {
        anchorId: anchor.id,
        result: {
          sessionId: "",
          anchorId: anchor.id,
          anchor: anchor.anchor,
          totalFrames: anchor.anchor.frameCount,
          totalChunks: anchor.chunks,
          processingTimeMs: anchor.anchor.processingTimeMs,
        },
      });
    },
    [navigation]
  );

  const renderItem = useCallback(
    ({ item }: { item: StoredAnchor }) => {
      const root = item.anchor.videoMerkleRoot;
      const shortRoot = root.length > 16
        ? `${root.slice(0, 8)}...${root.slice(-8)}`
        : root;
      const date = new Date(item.createdAt);
      const timeStr = date.toLocaleString();

      return (
        <Pressable style={styles.item} onPress={() => handleView(item)}>
          <View style={styles.itemHeader}>
            <Text style={styles.itemBadge}>VRC-48M</Text>
            <Text style={styles.itemTime}>{timeStr}</Text>
          </View>
          <Text style={styles.itemRoot}>{shortRoot}</Text>
          <View style={styles.itemMeta}>
            <Text style={styles.itemMetaText}>
              {item.chunks} chunks
            </Text>
            <Text style={styles.itemMetaText}>
              {item.durationS.toFixed(1)}s
            </Text>
            <Text style={styles.itemMetaText}>
              {item.anchor.width}x{item.anchor.height}
            </Text>
          </View>
          <Pressable
            style={styles.deleteBtn}
            onPress={() => handleDelete(item.id)}
          >
            <Text style={styles.deleteBtnText}>Delete</Text>
          </Pressable>
        </Pressable>
      );
    },
    [handleView, handleDelete]
  );

  return (
    <View style={styles.container}>
      <FlatList
        data={anchors}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyIcon}>&#x1f4f7;</Text>
            <Text style={styles.emptyTitle}>No anchors yet</Text>
            <Text style={styles.emptySubtitle}>
              Record a video to create your first topological anchor.
            </Text>
          </View>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.bg,
  },
  list: {
    padding: 16,
    gap: 12,
    paddingBottom: 40,
  },
  item: {
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 14,
    padding: 16,
  },
  itemHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  itemBadge: {
    fontSize: 10,
    fontWeight: "700",
    color: COLORS.accent,
    letterSpacing: 1,
    backgroundColor: "rgba(0, 240, 255, 0.1)",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: "hidden",
  },
  itemTime: {
    fontSize: 11,
    color: COLORS.muted,
  },
  itemRoot: {
    fontSize: 13,
    color: COLORS.text,
    fontFamily: "monospace",
    marginBottom: 8,
  },
  itemMeta: {
    flexDirection: "row",
    gap: 12,
    marginBottom: 8,
  },
  itemMetaText: {
    fontSize: 11,
    color: COLORS.muted,
  },
  deleteBtn: {
    alignSelf: "flex-end",
  },
  deleteBtnText: {
    fontSize: 12,
    color: COLORS.red,
    opacity: 0.6,
  },
  empty: {
    alignItems: "center",
    paddingTop: 80,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 12,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: "700",
    color: COLORS.text,
    marginBottom: 4,
  },
  emptySubtitle: {
    fontSize: 14,
    color: COLORS.muted,
    textAlign: "center",
    maxWidth: 260,
  },
});
