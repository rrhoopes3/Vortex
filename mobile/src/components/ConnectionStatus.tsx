/**
 * ConnectionStatus — Small indicator showing WebSocket connection state.
 */

import React from "react";
import { StyleSheet, Text, View } from "react-native";
import type { SessionState } from "../sdk/types";
import { COLORS } from "../utils/config";

interface ConnectionStatusProps {
  connected: boolean;
  state: SessionState;
}

const STATE_LABELS: Record<SessionState, string> = {
  idle: "Ready",
  connecting: "Connecting...",
  ready: "Connected",
  recording: "Recording",
  finalizing: "Anchoring...",
  done: "Done",
  error: "Error",
};

const STATE_COLORS: Record<SessionState, string> = {
  idle: COLORS.muted,
  connecting: COLORS.accent,
  ready: COLORS.green,
  recording: COLORS.red,
  finalizing: COLORS.purple,
  done: COLORS.green,
  error: COLORS.red,
};

export function ConnectionStatus({ connected, state }: ConnectionStatusProps) {
  const dotColor = connected ? STATE_COLORS[state] : COLORS.red;
  const label = connected ? STATE_LABELS[state] : "Disconnected";

  return (
    <View style={styles.container}>
      <View style={[styles.dot, { backgroundColor: dotColor }]} />
      <Text style={[styles.label, { color: dotColor }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: "rgba(0, 0, 0, 0.5)",
    borderRadius: 12,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  label: {
    fontSize: 12,
    fontWeight: "600",
    letterSpacing: 0.5,
  },
});
