# VRC-48M Camera — Kill Deepfakes With Topology

iOS camera app that anchors media at the moment of capture using 48D topological invariants. Record a video, watch chunks anchor in real-time, and get a tamper-proof proof that survives re-encoding but breaks under manipulation.

## Architecture

```
iPhone (React Native)                    Server (Flask + SocketIO)
+-------------------+                   +------------------------+
| VisionCamera      |  WebSocket        | StreamingVRC48M        |
| frame processor   | ──── frames ────> | process_frame()        |
|                   | <── chunks ──────  | chunk_complete events  |
| ChunkTimeline     |                   |                        |
| (live green bars) |  finalize ──────> | build Merkle tree      |
|                   | <── anchor ──────  | return MediaAnchor     |
+-------------------+                   +------------------------+
```

**Server-side hashing.** The heavy OpenCV/numpy feature extraction stays on the server. The phone captures frames, JPEG-compresses them, and streams over WebSocket at 10fps. Server runs `StreamingVRC48M` and sends back chunk results in real-time.

## Quick Start

### 1. Start the server

```bash
cd ..
pip install -e ".[dev]"
python -m forge.vortexchain.server
```

Server starts at `http://localhost:5000` with WebSocket support.

### 2. Configure the app

Edit `src/utils/config.ts` and set `DEFAULT_SERVER_URL` to your machine's LAN IP:

```typescript
export const DEFAULT_SERVER_URL = "http://192.168.1.30:5000";
```

### 3. Build and run on iOS

```bash
cd mobile
npm install
npx expo prebuild --platform ios
npx expo run:ios
```

Or use Expo Go for development:

```bash
npx expo start
```

## Screens

### Record
Camera view with a record button. When recording:
- Frames stream to the server at 10fps (every 3rd frame at 30fps capture)
- `ChunkTimeline` fills with green bars as chunks anchor in real-time
- Tap stop to finalize and build the Merkle tree

### Review
Post-recording display showing:
- Frame count, chunk count, duration, resolution
- Merkle root (the topological proof)
- Sample spectra visualization at 0%, 25%, 50%, 75%
- Share anchor as JSON

### Verify
Pick a video from the photo library, select an anchor, and verify. Returns authentic/tampered verdict with per-chunk breakdown and exact tampered time ranges.

### History
Browse and manage past anchors stored locally on device.

## SDK (`src/sdk/`)

The TypeScript SDK is framework-agnostic and can be extracted as a standalone npm package.

```typescript
import { VRC48MClient } from './sdk';

const client = new VRC48MClient({
  serverUrl: 'http://192.168.1.30:5000',
});

await client.connect();
await client.startSession();

client.on('chunk', (chunk) => {
  console.log(`Chunk ${chunk.chunkIndex} anchored — spectrum:`, chunk.spectrum);
});

// In your camera frame callback:
client.sendFrame(jpegArrayBuffer);

// When done recording:
const result = await client.finalize();
console.log('Merkle root:', result.anchor.videoMerkleRoot);
```

### SDK Modules

| File | Purpose |
|------|---------|
| `types.ts` | All TypeScript interfaces (config, chunks, anchors, errors) |
| `VRC48MClient.ts` | WebSocket client with EventEmitter pattern |
| `frameEncoder.ts` | Binary frame encoding (session_id + sequence + JPEG) |
| `sessionStore.ts` | Local anchor persistence via AsyncStorage |

## WebSocket Protocol

Binary frame transport for minimal overhead:

```
Client → Server:
  vrc48m:init     { fps, width, height, chunk_size, frame_skip }
  vrc48m:frame    [36B session_id][4B seq uint32 BE][JPEG bytes]
  vrc48m:finalize { session_id }
  vrc48m:abort    { session_id }

Server → Client:
  vrc48m:session_created  { session_id, config }
  vrc48m:chunk_complete   { chunk_index, spectrum, digest_hex }
  vrc48m:anchor_complete  { anchor, total_frames, total_chunks }
  vrc48m:error            { code, message }
```

## Frame Skip Strategy

Camera captures at 30fps but only every 3rd frame is sent (10fps). The server creates `StreamingVRC48M(chunk_size=10, fps=10.0)` so each chunk still represents ~1 second. The anchor records `source_fps`, `analysis_fps`, and `frame_skip` so verification applies matching subsampling.

The topological invariants hold at 10fps — perceptual features (gradients, DCT, color) are per-frame properties, and the tanh normalization in `normalize_sfp` absorbs larger optical flow magnitudes between skipped frames.

## Network Resilience

- Frame buffer holds up to 10 seconds of frames during disconnect
- Socket.IO auto-reconnects with exponential backoff
- On reconnect, buffered frames drain to server
- Recording does not stop on disconnect — just buffers

## Project Structure

```
mobile/
  app.json                    # Expo config (iOS permissions, plugins)
  package.json                # Dependencies
  tsconfig.json               # TypeScript config
  src/
    App.tsx                   # Tab navigation root
    screens/
      RecordScreen.tsx        # Camera + live anchoring
      ReviewScreen.tsx        # Post-recording anchor display
      VerifyScreen.tsx        # Video verification
      HistoryScreen.tsx       # Past anchors
    components/
      ChunkTimeline.tsx       # Animated chunk progress bar
      ConnectionStatus.tsx    # WebSocket connection indicator
      AnchorBadge.tsx         # Compact anchor display
    hooks/
      useVRC48M.ts            # React hook wrapping VRC48MClient
    sdk/
      index.ts                # Public exports
      types.ts                # TypeScript interfaces
      VRC48MClient.ts         # WebSocket streaming client
      frameEncoder.ts         # Binary frame encoding
      sessionStore.ts         # Local anchor persistence
    utils/
      config.ts               # Server URL, camera settings, colors
```

## Dependencies

- `react-native-vision-camera` v4 — frame processor with JPEG export
- `socket.io-client` — WebSocket transport
- `react-native-reanimated` — 60fps timeline animations
- `@react-navigation` — tab + stack navigation
- `expo-image-picker` — video selection for verification

## Why This Matters

Wrapping numbers are **non-differentiable** — zero gradient almost everywhere. Generative AI optimizes by following gradients. No gradient means no optimization path. This isn't a better deepfake detector. It's a mathematical wall.
