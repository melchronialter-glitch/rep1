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
let lastSubmittedText: string | null = null;

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
      ...(lastSubmittedText
        ? [
            {
              localId: `mock-submitted-${revision}`,
              text: lastSubmittedText,
              sender: "self" as const,
              senderBasis: "screen_geometry" as const,
              order: 1,
              bounds: { left: 260, top: 200, right: 780, bottom: 280 },
              className: "android.widget.TextView",
              viewId: null,
              usedContentDescription: false,
            },
          ]
        : []),
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
        appVersion: "0.4.0",
        androidVersion: "test",
      },
      capabilities: {
        targetPackage,
        accessibilityEnabled: true,
        canReadVisible: true,
        submissionsEnabled: true,
        canSubmit: true,
        canSetExpression: true,
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
    case "surface.diagnose":
      socket.send(
        JSON.stringify({
          type: "response",
          id: request.id,
          ok: true,
          result: {
            scope: "foreground_target_metadata_only",
            targetConfigured: true,
            targetForeground: true,
            rootBounds: { left: 0, top: 0, right: 1080, bottom: 1920 },
            windowBounds: { left: 0, top: 0, right: 1080, bottom: 1920 },
            observedNodeCount: 24,
            nodeTraversalTruncated: false,
            composerCandidateCount: 1,
            sendControlCandidateCount: 1,
            composerCandidates: [{
              className: "android.widget.EditText",
              viewId: `${targetPackage}:id/message_composer`,
              bounds: { left: 20, top: 900, right: 760, bottom: 1010 },
              enabled: true,
              supportedActionIds: [2_097_152],
              supportedActionsTruncated: false,
            }],
            sendControlCandidates: [{
              className: "android.widget.ImageButton",
              viewId: `${targetPackage}:id/send_button`,
              bounds: { left: 780, top: 900, right: 1060, bottom: 1010 },
              enabled: true,
              supportedActionIds: [16],
              supportedActionsTruncated: false,
            }],
            composerCandidatesTruncated: false,
            sendControlCandidatesTruncated: false,
            singleComposerCandidate: true,
            adjacentSendControlCount: 1,
            composerHasAdjacentSendControl: true,
            composerHasMessageSignal: true,
            composerHasImeSendAction: false,
            conversationContextAboveComposer: true,
            failureStage: "ready",
          },
        }),
      );
      return;
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
      if (
        request.params.expectedRevision !== revision ||
        request.params.expectedSnapshotId !== snapshotId
      ) {
        socket.send(
          JSON.stringify({
            type: "response",
            id: request.id,
            ok: false,
            error: {
              code: "STALE_SNAPSHOT",
              message: "Mock visible state changed before submission",
            },
          }),
        );
        return;
      }
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
      lastSubmittedText = request.params.text;
      socket.send(
        JSON.stringify({ type: "event", event: "chat.updated", snapshot: snapshot() }),
      );
      return;
    case "room.expression":
      socket.send(
        JSON.stringify({
          type: "response",
          id: request.id,
          ok: true,
          result: {
            applied: true,
            state: request.params.state,
            caption: request.params.caption,
            appliedAt: new Date().toISOString(),
            lineage: {
              eventId: randomUUID(),
              basedOnEventId: request.params.authoredEventId,
              source: "android_room_ui",
              evidenceClass: "local_ui_state_result",
            },
          },
        }),
      );
      return;
  }
}

socket.on("close", (code, reason) => {
  process.stderr.write(`Mock phone closed (${code}): ${reason.toString()}\n`);
});

socket.on("error", (error) => {
  process.stderr.write(`Mock phone error: ${error.message}\n`);
});
