import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
  MAX_EXPRESSION_CAPTION_CHARACTERS,
  MAX_SUBMIT_TEXT_CHARACTERS,
  MAX_VISIBLE_ITEMS,
  authoredExpressionStatusSchema,
  chatSnapshotSchema,
  expressionStateSchema,
  roomExpressionResultSchema,
  submitResultSchema,
  surfaceDiagnosticSchema,
} from "./protocol.js";
import { PhoneBroker, RosyTalkBridgeError } from "./phone-broker.js";
import type { LineageStore } from "./lineage.js";

const readOnlyAnnotations = {
  readOnlyHint: true,
  destructiveHint: false,
  openWorldHint: false,
} as const;

const submitAnnotations = {
  readOnlyHint: false,
  destructiveHint: true,
  openWorldHint: true,
} as const;

const expressionAnnotations = {
  readOnlyHint: false,
  destructiveHint: false,
  openWorldHint: false,
} as const;

function textAndStructured<T extends object>(structuredContent: T) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(structuredContent, null, 2) }],
    structuredContent: structuredContent as Record<string, unknown>,
  };
}

function toolError(error: unknown) {
  const publicError =
    error instanceof RosyTalkBridgeError
      ? { code: error.code, message: error.message }
      : { code: "INTERNAL_ERROR", message: "RosyTalk bridge request failed" };
  return {
    isError: true,
    content: [{ type: "text" as const, text: `${publicError.code}: ${publicError.message}` }],
  };
}

export function createRosyTalkMcpServer(
  broker: PhoneBroker,
  lineage: LineageStore,
): McpServer {
  const server = new McpServer(
    { name: "aster-android-rosytalk", version: "0.4.0" },
    {
      instructions:
        "Access only the exact Android app selected in the phone bridge. A snapshot contains only text visible in the current target window and is never a complete conversation history. Preserve every item's sender and senderBasis fields: screen_geometry is an inference, and unknown must remain unknown. Never attribute text to a person more confidently than the source data permits. Preserve lineage.eventId and parentEventId when comparing observations. rosytalk_diagnose_surface is metadata-only: do not use it to request, infer, or reconstruct UI content. Message submission is allowed only while the phone's per-session switch is enabled and must cite both expected_revision and expected_snapshot_id. A successful submit result means the UI action was performed; deliveryConfirmed is always false and must not be described as delivery. A room expression is an explicit state authored through rosytalk_set_expression; never infer an expression from message text, sentiment, or behavior. The durable lineage is metadata-only and is not a transcript.",
    },
  );

  server.registerTool(
    "rosytalk_status",
    {
      title: "Check RosyTalk bridge status",
      description:
        "Check the paired Android bridge, exact target package, accessibility state, per-session submission switch, durable-lineage availability, and latest ephemeral revision. Does not return message text.",
      inputSchema: {},
      outputSchema: {
        connected: z.boolean(),
        ready: z.boolean(),
        connectedAt: z.string().nullable(),
        device: z
          .object({
            id: z.string(),
            name: z.string(),
            appVersion: z.string(),
            androidVersion: z.string(),
          })
          .nullable(),
        capabilities: z
          .object({
            targetPackage: z.string().nullable(),
            accessibilityEnabled: z.boolean(),
            canReadVisible: z.boolean(),
            submissionsEnabled: z.boolean(),
            canSubmit: z.boolean(),
            canSetExpression: z.boolean(),
          })
          .nullable(),
        pendingRequests: z.number().int().nonnegative(),
        latestRevision: z.number().int().nonnegative().nullable(),
        lastUpdateAt: z.string().nullable(),
        lineageAvailable: z.boolean(),
        lineage: z.object({
          entries: z.number().int().nonnegative(),
          headSequence: z.number().int().nonnegative(),
          headHash: z.string().nullable(),
        }),
      },
      annotations: readOnlyAnnotations,
    },
    async () => textAndStructured({ ...broker.status(), lineage: lineage.summary() }),
  );

  server.registerTool(
    "rosytalk_room_status",
    {
      title: "Check Aster Room status",
      description:
        "Check whether the authenticated phone supports Aster Room expressions, whether the existing per-session action arm is enabled, and the last explicitly authored expression acknowledged by that phone connection. Does not infer expression or return message text.",
      inputSchema: {},
      outputSchema: {
        available: z.boolean(),
        sessionArmed: z.boolean(),
        canSetExpression: z.boolean(),
        expression: authoredExpressionStatusSchema.nullable(),
      },
      annotations: readOnlyAnnotations,
    },
    async () => textAndStructured(broker.roomStatus()),
  );

  server.registerTool(
    "rosytalk_diagnose_surface",
    {
      title: "Diagnose the visible RosyTalk surface",
      description:
        "Inspect bounded structural metadata for the exact configured foreground app to explain which safe chat-surface recognition gate passed or failed. Returns counts, geometry, class/view IDs, action IDs, and booleans only—never node text, hints, content descriptions, window titles, drafts, conversation identifiers, or content-derived hashes.",
      inputSchema: z.object({}).strict(),
      outputSchema: surfaceDiagnosticSchema,
      annotations: readOnlyAnnotations,
    },
    async () => {
      try {
        const diagnostic = surfaceDiagnosticSchema.parse(
          await broker.request("surface.diagnose", {}),
        );
        return textAndStructured(diagnostic);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "rosytalk_read_visible",
    {
      title: "Read visible RosyTalk window",
      description:
        "Read a bounded snapshot of text currently visible in the exact configured target app. It is explicitly incomplete; sender is either unknown or an inference whose basis is returned with each item.",
      inputSchema: {
        max_items: z.number().int().min(1).max(MAX_VISIBLE_ITEMS).default(100),
      },
      outputSchema: chatSnapshotSchema.shape,
      annotations: readOnlyAnnotations,
    },
    async ({ max_items }) => {
      try {
        const snapshot = chatSnapshotSchema.parse(
          await broker.request("chat.snapshot", { maxItems: max_items }),
        );
        return textAndStructured(snapshot);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "rosytalk_wait_for_update",
    {
      title: "Wait for a visible RosyTalk update",
      description:
        "Long-poll the relay's ephemeral in-memory update stream. Pass the last revision to wait for a newer visible target-window snapshot. Times out without inventing a reply.",
      inputSchema: {
        after_revision: z.number().int().nonnegative().optional(),
        timeout_seconds: z.number().int().min(1).max(55).default(45),
      },
      outputSchema: {
        updated: z.boolean(),
        snapshot: chatSnapshotSchema.nullable(),
        latestRevision: z.number().int().nonnegative().nullable(),
      },
      annotations: readOnlyAnnotations,
    },
    async ({ after_revision, timeout_seconds }) => {
      try {
        const snapshot = await broker.waitForUpdate(
          after_revision,
          timeout_seconds * 1_000,
        );
        return textAndStructured({
          updated: snapshot !== null,
          snapshot,
          latestRevision: snapshot?.revision ?? broker.status().latestRevision,
        });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "rosytalk_read_lineage",
    {
      title: "Read RosyTalk bridge lineage",
      description:
        "Read a bounded page of the append-only metadata chain that relates visible observations, submit requests, explicit expression requests, and local UI outcomes. It contains no conversation, submitted message text, or expression caption and is not proof of human authorship or remote delivery.",
      inputSchema: {
        after_sequence: z.number().int().nonnegative().default(0),
        limit: z.number().int().min(1).max(200).default(100),
      },
      outputSchema: {
        scope: z.literal("metadata_only"),
        records: z.array(z.object({}).passthrough()),
        headSequence: z.number().int().nonnegative(),
        headHash: z.string().nullable(),
        hasMore: z.boolean(),
        nextAfterSequence: z.number().int().nonnegative(),
      },
      annotations: readOnlyAnnotations,
    },
    async ({ after_sequence, limit }) =>
      textAndStructured(lineage.page(after_sequence, limit)),
  );

  server.registerTool(
    "rosytalk_submit_message",
    {
      title: "Submit a message in RosyTalk",
      description:
        "Put text into the exact configured target app only if its visible revision still matches the caller's last read or wait, then activate its unambiguous send control. Requires the phone's per-session submission switch. Success confirms only the accessibility UI action, never remote delivery.",
      inputSchema: {
        text: z
          .string()
          .min(1)
          .max(MAX_SUBMIT_TEXT_CHARACTERS)
          .refine((value) => value.trim().length > 0, "Message must contain non-whitespace text"),
        expected_revision: z
          .number()
          .int()
          .nonnegative()
          .max(Number.MAX_SAFE_INTEGER)
          .describe("Revision returned by the last read or wait_for_update call"),
        expected_snapshot_id: z
          .string()
          .uuid()
          .describe("lineage.eventId returned by the exact last read or wait_for_update call"),
      },
      outputSchema: submitResultSchema.shape,
      annotations: submitAnnotations,
    },
    async ({ text, expected_revision, expected_snapshot_id }) => {
      try {
        const result = submitResultSchema.parse(
          await broker.request("chat.submit", {
            text,
            expectedRevision: expected_revision,
            expectedSnapshotId: expected_snapshot_id,
          }),
        );
        return textAndStructured(result);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "rosytalk_set_expression",
    {
      title: "Set Aster Room expression",
      description:
        "Set an explicitly authored Aster Room expression on the authenticated phone. Requires the existing per-session action arm. The expression and optional caption come only from this tool input; the relay performs no sentiment inference.",
      inputSchema: {
        state: expressionStateSchema,
        caption: z
          .string()
          .max(MAX_EXPRESSION_CAPTION_CHARACTERS)
          .refine(
            (value) => value.trim().length > 0,
            "Caption must contain non-whitespace text",
          )
          .optional(),
      },
      outputSchema: roomExpressionResultSchema.shape,
      annotations: expressionAnnotations,
    },
    async ({ state, caption }) => {
      try {
        const result = roomExpressionResultSchema.parse(
          await broker.request("room.expression", {
            state,
            caption: caption ?? null,
          }),
        );
        return textAndStructured(result);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  return server;
}
