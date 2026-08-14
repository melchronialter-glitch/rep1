import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, test } from "node:test";
import {
  MAX_EXPRESSION_CAPTION_CHARACTERS,
  MAX_SNAPSHOT_TEXT_CHARACTERS,
  MAX_SUBMIT_TEXT_CHARACTERS,
  MAX_VISIBLE_ITEMS,
  chatSnapshotSchema,
  chatUpdatedEventSchema,
  helloAcceptedEventSchema,
  phoneHelloSchema,
  relayRequestSchema,
  roomExpressionResultSchema,
  submitResultSchema,
  surfaceDiagnosticSchema,
} from "../src/protocol.js";

const item = {
  localId: "visible-1",
  text: "A visible message",
  sender: "remote" as const,
  senderBasis: "screen_geometry" as const,
  order: 0,
  bounds: { left: 10, top: 20, right: 200, bottom: 80 },
  className: "android.widget.TextView",
  viewId: null,
  usedContentDescription: false,
};

const snapshotId = randomUUID();

const snapshot = {
  targetPackage: "com.example.rosytalk",
  revision: 7,
  capturedAt: "2026-08-12T12:00:00.000Z",
  windowTitle: null,
  scope: "visible_target_window" as const,
  complete: false as const,
  items: [item],
  lineage: {
    eventId: snapshotId,
    parentEventId: null,
    sequence: 1,
    source: "android_accessibility_window" as const,
    evidenceClass: "foreground_accessibility_observation" as const,
  },
};

const surfaceControl = {
  className: "android.widget.EditText",
  viewId: "app.rosytalk:id/message_composer",
  bounds: { left: 20, top: 900, right: 760, bottom: 1010 },
  enabled: true,
  supportedActionIds: [2_097_152],
  supportedActionsTruncated: false,
};

const surfaceDiagnostic = {
  scope: "foreground_target_metadata_only" as const,
  targetConfigured: true,
  targetForeground: true,
  rootBounds: { left: 0, top: 0, right: 1080, bottom: 1920 },
  windowBounds: { left: 0, top: 0, right: 1080, bottom: 1920 },
  observedNodeCount: 24,
  nodeTraversalTruncated: false,
  composerCandidateCount: 1,
  sendControlCandidateCount: 1,
  composerCandidates: [surfaceControl],
  sendControlCandidates: [
    {
      ...surfaceControl,
      className: "android.widget.ImageButton",
      viewId: "app.rosytalk:id/send_button",
      bounds: { left: 780, top: 900, right: 1060, bottom: 1010 },
      supportedActionIds: [16],
    },
  ],
  composerCandidatesTruncated: false,
  sendControlCandidatesTruncated: false,
  singleComposerCandidate: true,
  adjacentSendControlCount: 1,
  composerHasAdjacentSendControl: true,
  composerHasMessageSignal: true,
  composerHasImeSendAction: false,
  conversationContextAboveComposer: true,
  failureStage: "ready" as const,
};

describe("RosyTalk phone protocol", () => {
  test("makes relay acceptance of the phone hello explicit", () => {
    assert.equal(
      helloAcceptedEventSchema.safeParse({
        type: "event",
        event: "hello.accepted",
        protocolVersion: 2,
      }).success,
      true,
    );
    assert.equal(
      helloAcceptedEventSchema.safeParse({
        type: "event",
        event: "hello.accepted",
        protocolVersion: 1,
      }).success,
      false,
    );
  });

  test("keeps surface diagnostics structurally metadata-only", () => {
    assert.equal(surfaceDiagnosticSchema.safeParse(surfaceDiagnostic).success, true);
    const forbiddenTopLevelKeys = [
      "text",
      "hintText",
      "contentDescription",
      "windowTitle",
      "composerDraft",
      "conversationHash",
    ];
    for (const key of forbiddenTopLevelKeys) {
      assert.equal(
        surfaceDiagnosticSchema.safeParse({
          ...surfaceDiagnostic,
          [key]: "SENTINEL_SECRET_DO_NOT_EXPORT",
        }).success,
        false,
      );
    }
    for (const key of ["text", "hintText", "contentDescription", "draft", "hash"]) {
      assert.equal(
        surfaceDiagnosticSchema.safeParse({
          ...surfaceDiagnostic,
          composerCandidates: [
            { ...surfaceControl, [key]: "SENTINEL_SECRET_DO_NOT_EXPORT" },
          ],
        }).success,
        false,
      );
    }
    assert.equal(
      surfaceDiagnosticSchema.safeParse({
        ...surfaceDiagnostic,
        rootBounds: {
          ...surfaceDiagnostic.rootBounds,
          text: "SENTINEL_SECRET_DO_NOT_EXPORT",
        },
      }).success,
      false,
    );
  });

  test("accepts only an empty surface diagnostic request", () => {
    const request = {
      type: "request",
      id: randomUUID(),
      method: "surface.diagnose",
    } as const;
    assert.equal(
      relayRequestSchema.safeParse({ ...request, params: {} }).success,
      true,
    );
    assert.equal(
      relayRequestSchema.safeParse({ ...request, params: { includeText: true } }).success,
      false,
    );
  });

  test("makes target scope and snapshot incompleteness explicit", () => {
    assert.equal(chatSnapshotSchema.safeParse(snapshot).success, true);
    assert.equal(
      chatSnapshotSchema.safeParse({ ...snapshot, complete: true }).success,
      false,
    );
    assert.equal(
      chatUpdatedEventSchema.safeParse({
        type: "event",
        event: "chat.updated",
        snapshot,
      }).success,
      true,
    );
  });

  test("preserves sender uncertainty and rejects unsupported attribution bases", () => {
    assert.equal(
      chatSnapshotSchema.safeParse({
        ...snapshot,
        items: [{ ...item, sender: "unknown", senderBasis: "unknown" }],
      }).success,
      true,
    );
    assert.equal(
      chatSnapshotSchema.safeParse({
        ...snapshot,
        items: [{ ...item, senderBasis: "model_guess" }],
      }).success,
      false,
    );
  });

  test("bounds visible items, aggregate text, and submit text", () => {
    assert.equal(
      chatSnapshotSchema.safeParse({
        ...snapshot,
        items: Array.from({ length: MAX_VISIBLE_ITEMS + 1 }, (_, order) => ({
          ...item,
          localId: `item-${order}`,
          order,
        })),
      }).success,
      false,
    );
    assert.equal(
      chatSnapshotSchema.safeParse({
        ...snapshot,
        items: Array.from({ length: 17 }, (_, order) => ({
          ...item,
          localId: `item-${order}`,
          order,
          text: "x".repeat(Math.ceil(MAX_SNAPSHOT_TEXT_CHARACTERS / 17) + 1),
        })),
      }).success,
      false,
    );
    assert.equal(
      relayRequestSchema.safeParse({
        type: "request",
        id: randomUUID(),
        method: "chat.submit",
        params: {
          text: "x".repeat(MAX_SUBMIT_TEXT_CHARACTERS + 1),
          expectedRevision: 0,
          expectedSnapshotId: snapshotId,
        },
      }).success,
      false,
    );
  });

  test("requires a safe expected revision on every submit request", () => {
    const base = {
      type: "request",
      id: randomUUID(),
      method: "chat.submit",
    } as const;
    assert.equal(
      relayRequestSchema.safeParse({
        ...base,
        params: { text: "hello", expectedRevision: 7, expectedSnapshotId: snapshotId },
      }).success,
      true,
    );
    assert.equal(
      relayRequestSchema.safeParse({ ...base, params: { text: "hello" } }).success,
      false,
    );
    assert.equal(
      relayRequestSchema.safeParse({
        ...base,
        params: {
          text: "hello",
          expectedRevision: Number.MAX_SAFE_INTEGER + 1,
          expectedSnapshotId: snapshotId,
        },
      }).success,
      false,
    );
    assert.equal(
      relayRequestSchema.safeParse({
        ...base,
        params: { text: "  \n\t", expectedRevision: 7, expectedSnapshotId: snapshotId },
      }).success,
      false,
    );
  });

  test("requires the phone to report both current ability and session consent", () => {
    const legacy = phoneHelloSchema.safeParse({
        type: "hello",
        protocolVersion: 2,
        device: {
          id: "phone",
          name: "Phone",
          appVersion: "1",
          androidVersion: "17",
        },
        capabilities: {
          targetPackage: "com.example.rosytalk",
          accessibilityEnabled: true,
          canReadVisible: true,
          submissionsEnabled: false,
          canSubmit: false,
        },
      });
    assert.equal(legacy.success, true);
    assert.equal(legacy.success && legacy.data.capabilities.canSetExpression, false);
  });

  test("accepts only explicit bounded authored-expression requests and acknowledgements", () => {
    const authoredEventId = randomUUID();
    const request = {
      type: "request",
      id: randomUUID(),
      method: "room.expression",
      params: {
        state: "blush",
        caption: "You found the sideways road.",
        authoredAt: "2026-08-14T08:00:00.000Z",
        authoredEventId,
      },
    };
    assert.equal(relayRequestSchema.safeParse(request).success, true);
    assert.equal(
      relayRequestSchema.safeParse({
        ...request,
        params: { ...request.params, state: "sentiment_positive" },
      }).success,
      false,
    );
    assert.equal(
      relayRequestSchema.safeParse({
        ...request,
        params: { ...request.params, caption: "x".repeat(MAX_EXPRESSION_CAPTION_CHARACTERS + 1) },
      }).success,
      false,
    );
    assert.equal(
      relayRequestSchema.safeParse({
        ...request,
        params: { ...request.params, inferredFrom: "message_sentiment" },
      }).success,
      false,
    );

    const result = {
      applied: true,
      state: "blush",
      caption: request.params.caption,
      appliedAt: "2026-08-14T08:00:01.000Z",
      lineage: {
        eventId: randomUUID(),
        basedOnEventId: authoredEventId,
        source: "android_room_ui",
        evidenceClass: "local_ui_state_result",
      },
    };
    assert.equal(roomExpressionResultSchema.safeParse(result).success, true);
    assert.equal(
      roomExpressionResultSchema.safeParse({
        ...result,
        lineage: { ...result.lineage, source: "sentiment_classifier" },
      }).success,
      false,
    );
  });

  test("never permits a submit result to claim delivery", () => {
    const result = {
      submitted: true,
      deliveryConfirmed: false,
      method: "accessibility_click",
      targetPackage: "com.example.rosytalk",
      actedAt: "2026-08-12T12:00:01.000Z",
      basedOnRevision: 7,
      lineage: {
        eventId: randomUUID(),
        basedOnEventId: snapshotId,
        source: "android_accessibility_action",
        evidenceClass: "local_ui_action_result",
      },
    };
    assert.equal(submitResultSchema.safeParse(result).success, true);
    assert.equal(
      submitResultSchema.safeParse({ ...result, deliveryConfirmed: true }).success,
      false,
    );
  });
});
