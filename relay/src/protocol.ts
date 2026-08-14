import { z } from "zod";

export const PROTOCOL_VERSION = 2 as const;

// A snapshot is text-only and bounded both per item and in aggregate. This
// keeps an accessibility-tree mistake from becoming an unbounded WS frame.
export const MAX_PHONE_MESSAGE_BYTES = 2 * 1024 * 1024;
export const MAX_VISIBLE_ITEMS = 200;
export const MAX_ITEM_TEXT_CHARACTERS = 16_000;
export const MAX_SNAPSHOT_TEXT_CHARACTERS = 256 * 1024;
export const MAX_SUBMIT_TEXT_CHARACTERS = 16_000;
export const MAX_EXPRESSION_CAPTION_CHARACTERS = 160;
export const MAX_ID_CHARACTERS = 128;

const idSchema = z.string().min(1).max(MAX_ID_CHARACTERS);
const packageNameSchema = z
  .string()
  .min(3)
  .max(255)
  .regex(/^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$/);
const timestampSchema = z
  .string()
  .min(1)
  .max(64)
  .refine((value) => !Number.isNaN(Date.parse(value)), "Invalid timestamp");

export const snapshotLineageSchema = z.object({
  eventId: z.string().uuid(),
  parentEventId: z.string().uuid().nullable(),
  sequence: z.number().int().positive().max(Number.MAX_SAFE_INTEGER),
  source: z.literal("android_accessibility_window"),
  evidenceClass: z.literal("foreground_accessibility_observation"),
});

export type SnapshotLineage = z.infer<typeof snapshotLineageSchema>;

export const actionLineageSchema = z.object({
  eventId: z.string().uuid(),
  basedOnEventId: z.string().uuid(),
  source: z.literal("android_accessibility_action"),
  evidenceClass: z.literal("local_ui_action_result"),
});

export type ActionLineage = z.infer<typeof actionLineageSchema>;

export const expressionStateSchema = z.enum([
  "neutral",
  "thinking",
  "amused",
  "soft",
  "fierce",
  "flustered",
  "blush",
]);

export type ExpressionState = z.infer<typeof expressionStateSchema>;

export const expressionCaptionSchema = z
  .string()
  .max(MAX_EXPRESSION_CAPTION_CHARACTERS)
  .refine((value) => value.trim().length > 0, "Caption must contain non-whitespace text");

export const roomExpressionInputSchema = z.object({
  state: expressionStateSchema,
  caption: expressionCaptionSchema.nullable().optional(),
}).strict();

export type RoomExpressionInput = z.infer<typeof roomExpressionInputSchema>;

export const roomExpressionLineageSchema = z.object({
  eventId: z.string().uuid(),
  basedOnEventId: z.string().uuid(),
  source: z.literal("android_room_ui"),
  evidenceClass: z.literal("local_ui_state_result"),
}).strict();

export type RoomExpressionLineage = z.infer<typeof roomExpressionLineageSchema>;

export const relayMethodSchema = z.enum([
  "chat.snapshot",
  "chat.submit",
  "room.expression",
]);
export type RelayMethod = z.infer<typeof relayMethodSchema>;

export const phoneHelloSchema = z.object({
  type: z.literal("hello"),
  protocolVersion: z.literal(PROTOCOL_VERSION),
  device: z.object({
    id: idSchema,
    name: z.string().min(1).max(200),
    appVersion: z.string().min(1).max(50),
    androidVersion: z.string().min(1).max(50),
  }),
  capabilities: z.object({
    targetPackage: packageNameSchema.nullable(),
    accessibilityEnabled: z.boolean(),
    canReadVisible: z.boolean(),
    submissionsEnabled: z.boolean(),
    canSubmit: z.boolean(),
    // Protocol v2 extension. Older phone builds omit this and remain read/chat-only.
    canSetExpression: z.boolean().default(false),
  }),
});

export type PhoneHello = z.infer<typeof phoneHelloSchema>;

export const relayRequestSchema = z.discriminatedUnion("method", [
  z.object({
    type: z.literal("request"),
    id: z.string().uuid(),
    method: z.literal("chat.snapshot"),
    params: z.object({
      maxItems: z.number().int().min(1).max(MAX_VISIBLE_ITEMS),
    }),
  }),
  z.object({
    type: z.literal("request"),
    id: z.string().uuid(),
    method: z.literal("chat.submit"),
    params: z.object({
      text: z
        .string()
        .min(1)
        .max(MAX_SUBMIT_TEXT_CHARACTERS)
        .refine((value) => value.trim().length > 0, "Message must contain non-whitespace text"),
      expectedRevision: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
      expectedSnapshotId: z.string().uuid(),
    }),
  }),
  z.object({
    type: z.literal("request"),
    id: z.string().uuid(),
    method: z.literal("room.expression"),
    params: z.object({
      state: expressionStateSchema,
      caption: expressionCaptionSchema.nullable(),
      authoredAt: timestampSchema,
      authoredEventId: z.string().uuid(),
    }).strict(),
  }),
]);

export type RelayRequest = z.infer<typeof relayRequestSchema>;

export const phoneResponseSchema = z.discriminatedUnion("ok", [
  z.object({
    type: z.literal("response"),
    id: z.string().uuid(),
    ok: z.literal(true),
    result: z.unknown(),
  }),
  z.object({
    type: z.literal("response"),
    id: z.string().uuid(),
    ok: z.literal(false),
    error: z.object({
      code: z.string().min(1).max(100),
      message: z.string().min(1).max(1000),
    }),
  }),
]);

export type PhoneResponse = z.infer<typeof phoneResponseSchema>;

export const screenBoundsSchema = z
  .object({
    left: z.number().int().min(-100_000).max(100_000),
    top: z.number().int().min(-100_000).max(100_000),
    right: z.number().int().min(-100_000).max(100_000),
    bottom: z.number().int().min(-100_000).max(100_000),
  })
  .refine(
    ({ left, top, right, bottom }) => right >= left && bottom >= top,
    "Invalid screen bounds",
  );

export const visibleChatItemSchema = z.object({
  localId: idSchema,
  text: z.string().min(1).max(MAX_ITEM_TEXT_CHARACTERS),
  sender: z.enum(["self", "remote", "unknown"]),
  senderBasis: z.enum(["screen_geometry", "unknown"]),
  order: z.number().int().min(0).max(MAX_VISIBLE_ITEMS - 1),
  bounds: screenBoundsSchema,
  viewId: z.string().max(500).nullable(),
  className: z.string().max(500).nullable(),
  usedContentDescription: z.boolean(),
});

export type VisibleChatItem = z.infer<typeof visibleChatItemSchema>;

export const chatSnapshotSchema = z
  .object({
    revision: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    capturedAt: timestampSchema,
    targetPackage: packageNameSchema,
    windowTitle: z.string().max(512).nullable(),
    // Accessibility sees only the current target window, never the full thread.
    scope: z.literal("visible_target_window"),
    complete: z.literal(false),
    items: z.array(visibleChatItemSchema).max(MAX_VISIBLE_ITEMS),
    lineage: snapshotLineageSchema,
  })
  .superRefine(({ items }, context) => {
    const totalCharacters = items.reduce((total, item) => total + item.text.length, 0);
    if (totalCharacters > MAX_SNAPSHOT_TEXT_CHARACTERS) {
      context.addIssue({
        code: "custom",
        message: `Snapshot text exceeds ${MAX_SNAPSHOT_TEXT_CHARACTERS} characters`,
        path: ["items"],
      });
    }
  });

export type ChatSnapshot = z.infer<typeof chatSnapshotSchema>;

export const submitResultSchema = z.object({
  submitted: z.literal(true),
  // UI submission is not evidence that the remote service delivered the text.
  deliveryConfirmed: z.literal(false),
  targetPackage: packageNameSchema,
  method: z.enum(["accessibility_click", "ime_enter"]),
  actedAt: timestampSchema,
  basedOnRevision: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
  lineage: actionLineageSchema,
});

export type SubmitResult = z.infer<typeof submitResultSchema>;

export const roomExpressionResultSchema = z.object({
  applied: z.literal(true),
  state: expressionStateSchema,
  caption: expressionCaptionSchema.nullable(),
  appliedAt: timestampSchema,
  lineage: roomExpressionLineageSchema,
}).strict();

export type RoomExpressionResult = z.infer<typeof roomExpressionResultSchema>;

export const authoredExpressionStatusSchema = z.object({
  state: expressionStateSchema,
  caption: expressionCaptionSchema.nullable(),
  authoredAt: timestampSchema,
  authoredEventId: z.string().uuid(),
  appliedAt: timestampSchema,
  lineage: roomExpressionLineageSchema,
  authorship: z.literal("explicit_mcp_tool_input"),
}).strict();

export type AuthoredExpressionStatus = z.infer<typeof authoredExpressionStatusSchema>;

export const chatUpdatedEventSchema = z.object({
  type: z.literal("event"),
  event: z.literal("chat.updated"),
  snapshot: chatSnapshotSchema,
});

export type ChatUpdatedEvent = z.infer<typeof chatUpdatedEventSchema>;

export function parseResult(
  method: RelayMethod,
  value: unknown,
): ChatSnapshot | SubmitResult | RoomExpressionResult {
  switch (method) {
    case "chat.snapshot":
      return chatSnapshotSchema.parse(value);
    case "chat.submit":
      return submitResultSchema.parse(value);
    case "room.expression":
      return roomExpressionResultSchema.parse(value);
  }
}
