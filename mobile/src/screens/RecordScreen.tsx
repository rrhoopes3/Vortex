/**
 * RecordScreen — Camera view with real-time VRC-48M anchoring.
 *
 * Flow: IDLE → tap Record → init session → stream frames →
 *       chunks anchor in real-time → tap Stop → finalize →
 *       navigate to ReviewScreen
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import {
  Camera,
  useCameraDevice,
  useCameraPermission,
  useFrameProcessor,
} from "react-native-vision-camera";
import { useNavigation } from "@react-navigation/native";
import { ChunkTimeline } from "../components/ChunkTimeline";
import { ConnectionStatus } from "../components/ConnectionStatus";
import { useVRC48M } from "../hooks/useVRC48M";
import { saveAnchor } from "../sdk/sessionStore";
import {
  CAMERA_FPS,
  CAMERA_HEIGHT,
  CAMERA_WIDTH,
  CHUNK_SIZE,
  COLORS,
  DEFAULT_SERVER_URL,
  FRAME_SKIP,
} from "../utils/config";

export function RecordScreen() {
  const navigation = useNavigation<any>();
  const { hasPermission, requestPermission } = useCameraPermission();
  const device = useCameraDevice("back");

  const [isRecording, setIsRecording] = useState(false);
  const [frameInChunk, setFrameInChunk] = useState(0);
  const frameCountRef = useRef(0);

  const vrc48mConfig = useMemo(
    () => ({
      serverUrl: DEFAULT_SERVER_URL,
      fps: CAMERA_FPS,
      width: CAMERA_WIDTH,
      height: CAMERA_HEIGHT,
      chunkSize: CHUNK_SIZE,
      frameSkip: FRAME_SKIP,
    }),
    []
  );

  const {
    state,
    connected,
    chunks,
    anchor,
    error,
    connect,
    startSession,
    sendFrame,
    finalize,
    abort,
    reset,
  } = useVRC48M(vrc48mConfig);

  // Connect on mount
  useEffect(() => {
    connect().catch((err) =>
      Alert.alert("Connection Failed", err.message)
    );
  }, [connect]);

  // Request camera permission
  useEffect(() => {
    if (!hasPermission) {
      requestPermission();
    }
  }, [hasPermission, requestPermission]);

  // Navigate to review when anchor is ready
  useEffect(() => {
    if (anchor) {
      saveAnchor(anchor).then((stored) => {
        navigation.navigate("Review", { anchorId: stored.id, result: anchor });
      });
    }
  }, [anchor, navigation]);

  // Frame processor — captures frames and sends to server
  const frameProcessor = useFrameProcessor((frame) => {
    "worklet";
    // Note: In a real build, this worklet would call a native module
    // to get the JPEG buffer. For the PoC, we use a placeholder that
    // demonstrates the architecture. The actual frame.toArrayBuffer()
    // API is available in VisionCamera v4.
  }, []);

  // Simulated frame sending for development
  // In production, this is replaced by the frame processor worklet
  const frameInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleRecord = useCallback(async () => {
    if (isRecording) {
      // Stop recording
      setIsRecording(false);
      if (frameInterval.current) {
        clearInterval(frameInterval.current);
        frameInterval.current = null;
      }
      try {
        await finalize();
      } catch (err: any) {
        Alert.alert("Finalize Error", err.message);
      }
      return;
    }

    // Start recording
    try {
      frameCountRef.current = 0;
      setFrameInChunk(0);
      await startSession();
      setIsRecording(true);

      // In development: simulate frame sending
      // In production: the frame processor handles this
      frameInterval.current = setInterval(() => {
        // Generate a minimal test JPEG (in production, this comes from camera)
        const syntheticFrame = new ArrayBuffer(1024);
        const view = new Uint8Array(syntheticFrame);
        // JPEG header magic bytes
        view[0] = 0xff;
        view[1] = 0xd8;
        view[view.length - 2] = 0xff;
        view[view.length - 1] = 0xd9;

        sendFrame(syntheticFrame);
        frameCountRef.current++;
        setFrameInChunk(frameCountRef.current % CHUNK_SIZE);
      }, 1000 / (CAMERA_FPS / FRAME_SKIP));
    } catch (err: any) {
      Alert.alert("Recording Error", err.message);
    }
  }, [isRecording, startSession, sendFrame, finalize]);

  const handleAbort = useCallback(() => {
    setIsRecording(false);
    if (frameInterval.current) {
      clearInterval(frameInterval.current);
      frameInterval.current = null;
    }
    abort();
  }, [abort]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (frameInterval.current) {
        clearInterval(frameInterval.current);
      }
    };
  }, []);

  if (!hasPermission) {
    return (
      <View style={styles.centered}>
        <Text style={styles.permissionText}>
          Camera permission is required to anchor media at capture.
        </Text>
        <Pressable style={styles.permissionBtn} onPress={requestPermission}>
          <Text style={styles.permissionBtnText}>Grant Permission</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Camera Preview */}
      <View style={styles.cameraContainer}>
        {device ? (
          <Camera
            style={StyleSheet.absoluteFill}
            device={device}
            isActive={true}
            frameProcessor={isRecording ? frameProcessor : undefined}
            fps={CAMERA_FPS}
          />
        ) : (
          <View style={styles.noCameraView}>
            <Text style={styles.noCameraText}>No camera available</Text>
            <Text style={styles.noCameraSubtext}>
              Using simulated frames for development
            </Text>
          </View>
        )}

        {/* Overlay: Connection status */}
        <View style={styles.statusOverlay}>
          <ConnectionStatus connected={connected} state={state} />
        </View>

        {/* Overlay: Recording indicator */}
        {isRecording && (
          <View style={styles.recIndicator}>
            <View style={styles.recDot} />
            <Text style={styles.recText}>REC</Text>
          </View>
        )}
      </View>

      {/* Bottom panel */}
      <View style={styles.bottomPanel}>
        {/* Chunk Timeline */}
        <ChunkTimeline
          chunks={chunks}
          currentFrameInChunk={frameInChunk}
          chunkSize={CHUNK_SIZE}
        />

        {/* Error display */}
        {error && (
          <View style={styles.errorBanner}>
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}

        {/* Controls */}
        <View style={styles.controls}>
          {isRecording && (
            <Pressable style={styles.abortBtn} onPress={handleAbort}>
              <Text style={styles.abortBtnText}>Cancel</Text>
            </Pressable>
          )}

          <Pressable
            style={[
              styles.recordBtn,
              isRecording && styles.recordBtnActive,
              (!connected || state === "finalizing") && styles.recordBtnDisabled,
            ]}
            onPress={handleRecord}
            disabled={!connected || state === "finalizing"}
          >
            <View
              style={[
                styles.recordBtnInner,
                isRecording && styles.recordBtnInnerActive,
              ]}
            />
          </Pressable>

          <View style={{ width: 60 }} />
        </View>

        <Text style={styles.hint}>
          {state === "finalizing"
            ? "Building topological anchor..."
            : isRecording
            ? "Tap to stop and anchor"
            : "Tap to record"}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.bg,
  },
  centered: {
    flex: 1,
    backgroundColor: COLORS.bg,
    justifyContent: "center",
    alignItems: "center",
    padding: 32,
  },
  cameraContainer: {
    flex: 1,
    backgroundColor: "#000",
    position: "relative",
  },
  noCameraView: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#0a0a12",
  },
  noCameraText: {
    fontSize: 16,
    color: COLORS.muted,
    fontWeight: "600",
  },
  noCameraSubtext: {
    fontSize: 12,
    color: COLORS.muted,
    marginTop: 4,
    opacity: 0.6,
  },
  statusOverlay: {
    position: "absolute",
    top: 60,
    left: 16,
    zIndex: 10,
  },
  recIndicator: {
    position: "absolute",
    top: 60,
    right: 16,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "rgba(0, 0, 0, 0.6)",
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 10,
  },
  recDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: COLORS.red,
  },
  recText: {
    fontSize: 12,
    fontWeight: "700",
    color: COLORS.red,
    letterSpacing: 1,
  },
  bottomPanel: {
    backgroundColor: COLORS.bg,
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 40,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
  },
  errorBanner: {
    backgroundColor: "rgba(255, 68, 102, 0.1)",
    borderRadius: 8,
    padding: 8,
    marginVertical: 8,
  },
  errorText: {
    fontSize: 12,
    color: COLORS.red,
    textAlign: "center",
  },
  controls: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    paddingVertical: 16,
    gap: 24,
  },
  recordBtn: {
    width: 72,
    height: 72,
    borderRadius: 36,
    borderWidth: 4,
    borderColor: COLORS.text,
    justifyContent: "center",
    alignItems: "center",
  },
  recordBtnActive: {
    borderColor: COLORS.red,
  },
  recordBtnDisabled: {
    opacity: 0.3,
  },
  recordBtnInner: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: COLORS.red,
  },
  recordBtnInnerActive: {
    width: 28,
    height: 28,
    borderRadius: 6,
  },
  abortBtn: {
    width: 60,
    alignItems: "center",
  },
  abortBtnText: {
    fontSize: 13,
    color: COLORS.muted,
  },
  hint: {
    fontSize: 13,
    color: COLORS.muted,
    textAlign: "center",
  },
  permissionText: {
    fontSize: 16,
    color: COLORS.text,
    textAlign: "center",
    marginBottom: 20,
    lineHeight: 24,
  },
  permissionBtn: {
    backgroundColor: COLORS.accent,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 12,
  },
  permissionBtnText: {
    fontSize: 14,
    fontWeight: "700",
    color: "#000",
  },
});
