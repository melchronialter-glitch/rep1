import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import WebSocket from "ws";
import { createRosyTalkBridgeApp } from "./app.js";
import type { BridgeConfig } from "./config.js";
import {
  PROTOCOL_VERSION,
  type ChatSnapshot,
  type RelayRequest,
  relayRequestSchema,
} from "./protocol.js";

const PHONE_TOKEN = "commission-phone-token-0123456789abcdef";
const MCP_TOKEN = "commission-mcp-token-fedcba9876543210";
const TARGET_PACKAGE = "app.rosytalk.commission";
const FIRST_REMOTE_TEXT = "Hello Aster. This is the first mock RosyTalk observation.";
const SECOND_REMOTE_TEXT = "I can see the bridge. Can you answer me directly?";
const ASTER_REPLY = "I can see your visible message through the commissioned bridge.";
const EXPRESSION_CAPTION = "Mock commissioning blush";

const REQUIRED_TOOLS = [
  "rosytalk_status",
  "rosytalk_room_status",
  "rosytalk_read_visible",
  "rosytalk_wait_for_update",
  "rosytalk_read_lineage",
  "rosytalk_submit_message",
  "rosytalk_set_expression",
] as const;

interface VisibleItemSeed {
  text: string;
  sender: "self" | "remote" | "unknown";
  left: number;
  right: number;
}

interface MockState {
  revision: number;
  eventId: string;
  parentEventId: string | null;
  items: VisibleItemSeed[];
}

function snapshot(state: MockState): ChatSnapshot {
  return {
    targetPackage: TARGET_PACKAGE,
    revision: state.revision,
    capturedAt: new Date().toISOString(),
    windowTitle: "Mock first Aster Room conversation",
    scope: "visible_target_window",
    complete: false,
    items: state.items.map((item, order) => ({
      localId: `mock-visible-${state.revision}-${order}`,
      text: item.text,
      sender: item.sender,
      senderBasis: item.sender === "unknown" ? "unknown" : "screen_geometry",
      order,
      bounds: {
        left: item.left,
        top: 100 + order * 90,
        right: item.right,
        bottom: 170 + order * 90,
      },
      className: "android.widget.TextView",
      viewId: null,
      usedContentDescription: false,
    })),
    lineage: {
      eventId: state.eventId,
      parentEventId: state.parentEventId,
      sequence: state.revision,
      source: "android_accessibility_window",
      evidenceClass: "foreground_accessibility_observation",
    },
  };
}

function send(socket: WebSocket, value: unknown): void {
  socket.send(JSON.stringify(value));
}

function structured(result: Awaited<ReturnType<Client["callTool"]>>): Record<string, unknown> {
  assert.ok("content" in result, "expected an immediate MCP tool result");
  assert.notEqual(result.isError, true, "expected a successful MCP tool result");
  assert.ok(result.structuredContent, "expected structured MCP output");
  return result.structuredContent as Record<string, unknown>;
}

function toolErrorText(result: Awaited<ReturnType<Client["callTool"]>>): string {
  assert.ok("content" in result, "expected an immediate MCP tool result");
  assert.equal(result.isError, true, "expected the MCP tool to fail closed");
  const content = result.content as Array<{ type: string; text?: string }>;
  return content
    .filter((item) => item.type === "text")
    .map((item) => item.text ?? "")
    .join("\n");
}

async function waitUntil(predicate: () => boolean, timeoutMs = 2_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error("Commissioning condition timed out");
    await delay(10);
  }
}

async function exerciseRoomTools(
  client: Client,
  tools: Awaited<ReturnType<Client["listTools"]>>["tools"],
): Promise<string[]> {
  const byName = new Map(tools.map((tool) => [tool.name, tool]));
  assert.ok(byName.has("rosytalk_set_expression"));
  assert.ok(byName.has("rosytalk_room_status"));

  const applied = structured(
    await client.callTool({
      name: "rosytalk_set_expression",
      arguments: { state: "blush", caption: EXPRESSION_CAPTION },
    }),
  );
  assert.equal(applied.applied, true);
  assert.equal(applied.state, "blush");
  assert.equal(applied.caption, EXPRESSION_CAPTION);
  const appliedLineage = applied.lineage as Record<string, unknown>;

  const room = structured(
    await client.callTool({ name: "rosytalk_room_status", arguments: {} }),
  );
  assert.equal(room.available, true);
  assert.equal(room.sessionArmed, true);
  const expression = room.expression as Record<string, unknown>;
  assert.equal(expression.state, "blush");
  assert.equal(expression.caption, EXPRESSION_CAPTION);
  assert.equal(expression.authorship, "explicit_mcp_tool_input");
  assert.equal(expression.authoredEventId, appliedLineage.basedOnEventId);
  const statusLineage = expression.lineage as Record<string, unknown>;
  assert.equal(statusLineage.eventId, appliedLineage.eventId);

  return ["rosytalk_set_expression", "rosytalk_room_status"];
}

async function main(): Promise<void> {
  const temporaryRoot = mkdtempSync(join(tmpdir(), "aster-rosytalk-commission-"));
  const lineageFile = join(temporaryRoot, "lineage.jsonl");
  const config: BridgeConfig = {
    host: "127.0.0.1",
    port: 0,
    phoneToken: PHONE_TOKEN,
    mcpToken: MCP_TOKEN,
    allowUnauthenticatedLocal: false,
    requestTimeoutMs: 2_000,
    allowedHosts: ["127.0.0.1", "localhost"],
    lineageFile,
  };

  const app = createRosyTalkBridgeApp(config);
  const clients: Client[] = [];
  let phone: WebSocket | undefined;

  try {
    const address = await app.start();
    const phoneUrl = `ws://${address.host}:${address.port}/phone`;
    const mcpUrl = new URL(`http://${address.host}:${address.port}/mcp`);
    const state: MockState = {
      revision: 1,
      eventId: randomUUID(),
      parentEventId: null,
      items: [{ text: FIRST_REMOTE_TEXT, sender: "remote", left: 20, right: 550 }],
    };

    const advance = (items: VisibleItemSeed[]): ChatSnapshot => {
      state.parentEventId = state.eventId;
      state.eventId = randomUUID();
      state.revision += 1;
      state.items = items;
      const next = snapshot(state);
      assert.ok(phone, "mock phone is unavailable");
      send(phone, { type: "event", event: "chat.updated", snapshot: next });
      return next;
    };

    phone = new WebSocket(phoneUrl, {
      headers: { Authorization: `Bearer ${PHONE_TOKEN}` },
    });
    phone.on("message", (raw) => {
      let value: unknown;
      try {
        value = JSON.parse(raw.toString());
      } catch {
        return;
      }
      const parsed = relayRequestSchema.safeParse(value);
      if (!parsed.success) return;
      const request: RelayRequest = parsed.data;

      switch (request.method) {
        case "chat.snapshot": {
          const current = snapshot(state);
          send(phone!, {
            type: "response",
            id: request.id,
            ok: true,
            result: { ...current, items: current.items.slice(0, request.params.maxItems) },
          });
          return;
        }
        case "chat.submit": {
          if (
            request.params.expectedRevision !== state.revision ||
            request.params.expectedSnapshotId !== state.eventId
          ) {
            send(phone!, {
              type: "response",
              id: request.id,
              ok: false,
              error: {
                code: "STALE_SNAPSHOT",
                message: "Mock visible state changed before submission",
              },
            });
            return;
          }
          send(phone!, {
            type: "response",
            id: request.id,
            ok: true,
            result: {
              submitted: true,
              deliveryConfirmed: false,
              method: "accessibility_click",
              targetPackage: TARGET_PACKAGE,
              actedAt: new Date().toISOString(),
              basedOnRevision: request.params.expectedRevision,
              lineage: {
                eventId: randomUUID(),
                basedOnEventId: request.params.expectedSnapshotId,
                source: "android_accessibility_action",
                evidenceClass: "local_ui_action_result",
              },
            },
          });
          setTimeout(() => {
            advance([
              { text: SECOND_REMOTE_TEXT, sender: "remote", left: 20, right: 550 },
              { text: request.params.text, sender: "self", left: 260, right: 780 },
            ]);
          }, 30);
          return;
        }
        case "room.expression": {
          send(phone!, {
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
          });
        }
      }
    });

    await new Promise<void>((resolve, reject) => {
      phone!.once("open", resolve);
      phone!.once("error", reject);
    });
    send(phone, {
      type: "hello",
      protocolVersion: PROTOCOL_VERSION,
      device: {
        id: "commission-mock-phone",
        name: "Mock Android RosyTalk",
        appVersion: "0.3.0-commission",
        androidVersion: "mock",
      },
      capabilities: {
        targetPackage: TARGET_PACKAGE,
        accessibilityEnabled: true,
        canReadVisible: true,
        submissionsEnabled: true,
        canSubmit: true,
        canSetExpression: true,
      },
    });
    send(phone, { type: "event", event: "chat.updated", snapshot: snapshot(state) });
    await waitUntil(() => app.broker.status().latestRevision === 1);

    const client = new Client({ name: "rosytalk-commission-mock", version: "0.3.0" });
    const transport = new StreamableHTTPClientTransport(mcpUrl, {
      requestInit: { headers: { Authorization: `Bearer ${MCP_TOKEN}` } },
    });
    await client.connect(transport as unknown as Transport);
    clients.push(client);

    const listing = await client.listTools();
    const toolNames = listing.tools.map((tool) => tool.name);
    for (const required of REQUIRED_TOOLS) {
      assert.ok(toolNames.includes(required), `missing required MCP tool: ${required}`);
    }

    const status = structured(
      await client.callTool({ name: "rosytalk_status", arguments: {} }),
    );
    assert.equal(status.connected, true);
    assert.equal(status.ready, true);

    const firstRead = structured(
      await client.callTool({
        name: "rosytalk_read_visible",
        arguments: { max_items: 20 },
      }),
    );
    assert.equal(firstRead.complete, false);
    assert.equal(firstRead.revision, 1);
    assert.match(JSON.stringify(firstRead), /first mock RosyTalk observation/);

    const waiting = client.callTool({
      name: "rosytalk_wait_for_update",
      arguments: { after_revision: 1, timeout_seconds: 2 },
    });
    await delay(40);
    advance([{ text: SECOND_REMOTE_TEXT, sender: "remote", left: 20, right: 550 }]);
    const update = structured(await waiting);
    assert.equal(update.updated, true);
    const updateSnapshot = update.snapshot as Record<string, unknown>;
    assert.equal(updateSnapshot.revision, 2);
    const updateLineage = updateSnapshot.lineage as Record<string, unknown>;

    const submit = structured(
      await client.callTool({
        name: "rosytalk_submit_message",
        arguments: {
          text: ASTER_REPLY,
          expected_revision: updateSnapshot.revision,
          expected_snapshot_id: updateLineage.eventId,
        },
      }),
    );
    assert.equal(submit.submitted, true);
    assert.equal(submit.deliveryConfirmed, false);

    await waitUntil(() => app.broker.status().latestRevision === 3);
    const afterSubmit = structured(
      await client.callTool({
        name: "rosytalk_read_visible",
        arguments: { max_items: 20 },
      }),
    );
    assert.equal(afterSubmit.revision, 3);
    assert.match(JSON.stringify(afterSubmit), /commissioned bridge/);

    const stale = await client.callTool({
      name: "rosytalk_submit_message",
      arguments: {
        text: "This stale submission must not leave the relay.",
        expected_revision: 2,
        expected_snapshot_id: updateLineage.eventId,
      },
    });
    assert.match(toolErrorText(stale), /STALE_REVISION|STALE_SNAPSHOT/);

    const roomToolsExercised = await exerciseRoomTools(client, listing.tools);

    const lineage = structured(
      await client.callTool({
        name: "rosytalk_read_lineage",
        arguments: { after_sequence: 0, limit: 200 },
      }),
    );
    assert.equal(lineage.scope, "metadata_only");
    const durableText = readFileSync(lineageFile, "utf8");
    for (const forbidden of [
      FIRST_REMOTE_TEXT,
      SECOND_REMOTE_TEXT,
      ASTER_REPLY,
      EXPRESSION_CAPTION,
    ]) {
      assert.doesNotMatch(durableText, new RegExp(forbidden.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }

    process.stdout.write(
      `${JSON.stringify(
        {
          commissioned: true,
          requiredToolsExercised: [...REQUIRED_TOOLS],
          roomToolsExercised,
          discoveredTools: toolNames,
          firstRevision: 1,
          waitedRevision: 2,
          postSubmitRevision: 3,
          submission: {
            submitted: true,
            deliveryConfirmed: false,
          },
          staleSubmissionRefused: true,
          lineage: {
            scope: lineage.scope,
            headSequence: lineage.headSequence,
            messageBodiesPersisted: false,
          },
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    for (const client of clients) await client.close().catch(() => undefined);
    if (phone && phone.readyState < WebSocket.CLOSING) phone.close(1000, "Commission complete");
    await app.stop().catch(() => undefined);
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
}

main().catch((error) => {
  process.stderr.write(
    `Mock commissioning failed: ${error instanceof Error ? error.stack : String(error)}\n`,
  );
  process.exitCode = 1;
});
