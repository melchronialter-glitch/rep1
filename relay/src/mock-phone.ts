import WebSocket from "ws";
import { randomUUID } from "node:crypto";
import {
  PROTOCOL_VERSION,
  type ChatSnapshot,
  relayRequestSchema,
  type RelayRequest,
} from "./protocol.js";

const relayUrl = process.env.PHONE_URL ?? "ws://127.0.0.1:8787/phone";
const token = process.env.PHONE_TOKEN;
if (!token) throw new Error("PHONE_TOKEN is required");

const targetPackage = process.env.TARGET_PACKAGE ?? "com.example.rosytalk";
let revision = 1;
let snapshotId = randomUUID();
let parentSnapshotId: string | null = null;

function snapshot(): ChatSnapshot {
  return {
    targetPackage,
    revision,
    capturedAt: new Date().toISOString(),
    windowTitle: "Mock RosyTalk conversation",
    scope: "visible_target_window",
    complete: false,
    items: [
      {
        localId: "mock-visible-item",
        text: "Hello from the mock visible window",
        sender: "remote",
        senderBasis: "screen_geometry",
        order: 0,
        bounds: { left: 20, top: 100, right: 600, bottom: 180 },
        className: "android.widget.TextView",
        viewId: null,
        usedContentDescription: false,
      },
    ],
    lineage: {
      eventId: snapshotId,
      parentEventId: parentSnapshotId,
      sequence: revision,
      source: "android_accessibility_window",
      evidenceClass: "foreground_accessibility_observation",
    },
  };
}

const socket = new WebSocket(relayUrl, {
  headers: { Authorization: `Bearer ${token}` },
});

socket.on("open", () => {
  socket.send(
    JSON.stringify({
      type: "hello",
      protocolVersion: PROTOCOL_VERSION,
      device: {
        id: "mock-phone",
        name: "Mock Android RosyTalk",
        appVersion: "0.1.0",
        androidVersion: "test",
      },
      capabilities: {
        targetPackage,
        accessibilityEnabled: true,
        canReadVisible: true,
        submissionsEnabled: true,
        canSubmit: true,
      },
    }),
  );
  socket.send(JSON.stringify({ type: "event", event: "chat.updated", snapshot: snapshot() }));
  process.stderr.write(`Mock phone connected to ${relayUrl}\n`);
});

socket.on("message", (raw) => {
  const parsed = relayRequestSchema.safeParse(JSON.parse(raw.toString()));
  if (!parsed.success) return;
  respond(parsed.data);
});

function respond(request: RelayRequest): void {
  switch (request.method) {
    case "chat.snapshot":
      socket.send(
        JSON.stringify({
          type: "response",
          id: request.id,
          ok: true,
          result: { ...snapshot(), items: snapshot().items.slice(0, request.params.maxItems) },
        }),
      );
      return;
    case "chat.submit":
      socket.send(
        JSON.stringify({
          type: "response",
          id: request.id,
          ok: true,
          result: {
            submitted: true,
            deliveryConfirmed: false,
            method: "accessibility_click",
            targetPackage,
            actedAt: new Date().toISOString(),
            basedOnRevision: request.params.expectedRevision,
            lineage: {
              eventId: randomUUID(),
              basedOnEventId: request.params.expectedSnapshotId,
              source: "android_accessibility_action",
              evidenceClass: "local_ui_action_result",
            },
          },
        }),
      );
      parentSnapshotId = snapshotId;
      snapshotId = randomUUID();
      revision += 1;
  }
}

socket.on("close", (code, reason) => {
  process.stderr.write(`Mock phone closed (${code}): ${reason.toString()}\n`);
});

socket.on("error", (error) => {
  process.stderr.write(`Mock phone error: ${error.message}\n`);
});
