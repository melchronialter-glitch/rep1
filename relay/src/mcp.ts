import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
  MAX_SUBMIT_TEXT_CHARACTERS,
  MAX_VISIBLE_ITEMS,
  chatSnapshotSchema,
  submitResultSchema,
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
    { name: "aster-android-rosytalk", version: "0.2.0" },
    {
      instructions:
        "Access only the exact Android app selected in the phone bridge. A snapshot contains only text visible in the current target window and is never a complete conversation history. Preserve every item's sender and senderBasis fields: screen_geometry is an inference, and unknown must remain unknown. Never attribute text to a person more confidently than the source data permits. Preserve lineage.eventId and parentEventId when comparing observations. Message submission is allowed only while the phone's per-session switch is enabled and must cite both expected_revision and expected_snapshot_id. A successful submit result means the UI action was performed; deliveryConfirmed is always false and must not be described as delivery. The durable lineage is metadata-only and is not a transcript.",
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
        "Read a bounded page of the append-only metadata chain that relates visible observations, submit requests, and local UI outcomes. It contains no conversation or submitted message text and is not proof of human authorship or remote delivery.",
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

  return server;
}
