import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";
import { mkdtempSync, renameSync, rmSync } from "node:fs";
import type { ServerResponse } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { describe, test, type TestContext } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import WebSocket from "ws";
import {
  createRosyTalkBridgeApp,
  registerMcpResponseCleanup,
  type RosyTalkBridgeApp,
} from "../src/app.js";
import type { BridgeConfig } from "../src/config.js";
import {
  PROTOCOL_VERSION,
  type ChatSnapshot,
  type PhoneHello,
  type RelayRequest,
  type SurfaceDiagnostic,
  helloAcceptedEventSchema,
  relayRequestSchema,
} from "../src/protocol.js";

const PHONE_TOKEN = "phone-integration-test-token";
const MCP_TOKEN = "mcp-integration-test-token";
const TARGET_PACKAGE = "com.example.rosytalk";
const lineageIds = new Map<number, string>();

function lineageId(revision: number): string {
  const existing = lineageIds.get(revision);
  if (existing) return existing;
  const value = randomUUID();
  lineageIds.set(revision, value);
  return value;
}

type ToolCallResult = Awaited<ReturnType<Client["callTool"]>>;
type ImmediateToolResult = Extract<ToolCallResult, { content: unknown }>;
type PhoneResponder = (request: RelayRequest, socket: WebSocket) => void;

interface PhoneConnection {
  requests: RelayRequest[];
  socket: WebSocket;
}

interface Harness {
  app: RosyTalkBridgeApp;
  baseUrl: string;
  mcpUrl: URL;
  phoneUrl: string;
  clients: Client[];
  phones: WebSocket[];
}

function snapshot(revision: number, text = "Visible remote text"): ChatSnapshot {
  return {
    targetPackage: TARGET_PACKAGE,
    revision,
    capturedAt: new Date().toISOString(),
    windowTitle: null,
    scope: "visible_target_window",
    complete: false,
    items: [
      {
        localId: `visible-${revision}`,
        text,
        sender: "remote",
        senderBasis: "screen_geometry",
        order: 0,
        bounds: { left: 10, top: 100, right: 500, bottom: 180 },
        className: "android.widget.TextView",
        viewId: null,
        usedContentDescription: false,
      },
    ],
    lineage: {
      eventId: lineageId(revision),
      parentEventId: revision > 1 ? lineageId(revision - 1) : null,
      sequence: revision,
      source: "android_accessibility_window",
      evidenceClass: "foreground_accessibility_observation",
    },
  };
}

function surfaceDiagnostic(): SurfaceDiagnostic {
  return {
    scope: "foreground_target_metadata_only",
    targetConfigured: true,
    targetForeground: true,
    rootBounds: { left: 0, top: 0, right: 1080, bottom: 1920 },
    windowBounds: { left: 0, top: 0, right: 1080, bottom: 1920 },
    observedNodeCount: 24,
    nodeTraversalTruncated: false,
    composerCandidateCount: 1,
    sendControlCandidateCount: 1,
    composerCandidates: [
      {
        className: "android.widget.EditText",
        viewId: "app.rosytalk:id/message_composer",
        bounds: { left: 20, top: 900, right: 760, bottom: 1010 },
        enabled: true,
        supportedActionIds: [2_097_152],
        supportedActionsTruncated: false,
      },
    ],
    sendControlCandidates: [
      {
        className: "android.widget.ImageButton",
        viewId: "app.rosytalk:id/send_button",
        bounds: { left: 780, top: 900, right: 1060, bottom: 1010 },
        enabled: true,
        supportedActionIds: [16],
        supportedActionsTruncated: false,
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
    failureStage: "ready",
  };
}

function config(overrides: Partial<BridgeConfig> = {}): BridgeConfig {
  return {
    host: "127.0.0.1",
    port: 0,
    phoneToken: PHONE_TOKEN,
    mcpToken: MCP_TOKEN,
    allowUnauthenticatedLocal: false,
    requestTimeoutMs: 250,
    allowedHosts: undefined,
    lineageFile: `/tmp/aster-rosytalk-test-${randomUUID()}.jsonl`,
    ...overrides,
  };
}

async function startHarness(
  t: TestContext,
  overrides: Partial<BridgeConfig> = {},
): Promise<Harness> {
  const app = createRosyTalkBridgeApp(config(overrides));
  const { host, port } = await app.start();
  const baseUrl = `http://${host}:${port}`;
  const harness: Harness = {
    app,
    baseUrl,
    mcpUrl: new URL("/mcp", baseUrl),
    phoneUrl: `ws://${host}:${port}/phone`,
    clients: [],
    phones: [],
  };

  t.after(async () => {
    for (const client of harness.clients) {
      await client.close().catch(() => undefined);
    }
    await app.stop();
  });

  return harness;
}

async function waitUntil(predicate: () => boolean, timeoutMs = 1_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error("Condition was not met before timeout");
    await delay(5);
  }
}

async function connectPhone(
  harness: Harness,
  options: {
    capabilities?: Partial<PhoneHello["capabilities"]>;
    responder?: PhoneResponder;
  } = {},
): Promise<PhoneConnection> {
  const requests: RelayRequest[] = [];
  let helloAccepted = false;
  const socket = new WebSocket(harness.phoneUrl, {
    headers: { Authorization: `Bearer ${PHONE_TOKEN}` },
  });

  socket.on("message", (raw) => {
    let value: unknown;
    try {
      value = JSON.parse(raw.toString());
    } catch {
      return;
    }
    if (helloAcceptedEventSchema.safeParse(value).success) {
      helloAccepted = true;
      return;
    }
    const parsed = relayRequestSchema.safeParse(value);
    if (!parsed.success) return;
    requests.push(parsed.data);
    options.responder?.(parsed.data, socket);
  });

  await new Promise<void>((resolve, reject) => {
    socket.once("open", resolve);
    socket.once("error", reject);
  });
  harness.phones.push(socket);

  socket.send(
    JSON.stringify({
      type: "hello",
      protocolVersion: PROTOCOL_VERSION,
      device: {
        id: "mock-phone",
        name: "Mock Android RosyTalk",
        appVersion: "0.1.0-test",
        androidVersion: "test",
      },
      capabilities: {
        targetPackage: TARGET_PACKAGE,
        accessibilityEnabled: true,
        canReadVisible: true,
        submissionsEnabled: true,
        canSubmit: true,
        canSetExpression: true,
        ...options.capabilities,
      },
    }),
  );
  await waitUntil(() => harness.app.broker.status().ready && helloAccepted);

  return { requests, socket };
}

function sendOk(socket: WebSocket, request: RelayRequest, result: unknown): void {
  socket.send(JSON.stringify({ type: "response", id: request.id, ok: true, result }));
}

function sendError(
  socket: WebSocket,
  request: RelayRequest,
  code: string,
  message: string,
): void {
  socket.send(
    JSON.stringify({ type: "response", id: request.id, ok: false, error: { code, message } }),
  );
}

function happyResponder(request: RelayRequest, socket: WebSocket): void {
  switch (request.method) {
    case "surface.diagnose":
      sendOk(socket, request, surfaceDiagnostic());
      return;
    case "chat.snapshot":
      sendOk(socket, request, snapshot(1));
      return;
    case "chat.submit":
      sendOk(socket, request, {
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
      });
      return;
    case "room.expression":
      sendOk(socket, request, {
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
      });
      return;
  }
}

async function connectMcp(harness: Harness, token = MCP_TOKEN): Promise<Client> {
  const client = new Client({ name: "rosytalk-relay-integration-tests", version: "1.0.0" });
  const transport = new StreamableHTTPClientTransport(harness.mcpUrl, {
    requestInit: { headers: { Authorization: `Bearer ${token}` } },
  });
  await client.connect(transport as unknown as Transport);
  harness.clients.push(client);
  return client;
}

function immediate(result: ToolCallResult): ImmediateToolResult {
  assert.ok("content" in result, "expected an immediate MCP tool result");
  return result as ImmediateToolResult;
}

function structured(result: ImmediateToolResult): Record<string, unknown> {
  assert.ok(result.structuredContent, "expected structured tool output");
  return result.structuredContent;
}

function errorText(result: ImmediateToolResult): string {
  assert.equal(result.isError, true);
  const text = result.content.find((item) => item.type === "text");
  assert.ok(text && text.type === "text");
  return text.text;
}

describe("RosyTalk relay integration", () => {
  test("cleans up per-request MCP resources exactly once", async () => {
    const response = new EventEmitter() as unknown as ServerResponse;
    let transportCloseCount = 0;
    let serverCloseCount = 0;
    const cleanup = registerMcpResponseCleanup(
      response,
      {
        close: async () => {
          transportCloseCount += 1;
        },
      },
      {
        close: async () => {
          serverCloseCount += 1;
        },
      },
    );

    response.emit("finish");
    response.emit("close");
    await cleanup();
    await cleanup();

    assert.equal(transportCloseCount, 1);
    assert.equal(serverCloseCount, 1);
    assert.equal(response.listenerCount("finish"), 0);
    assert.equal(response.listenerCount("close"), 0);
  });

  test("rejects unauthorized phone and MCP clients", async (t) => {
    const harness = await startHarness(t);

    const statusCode = await new Promise<number>((resolve, reject) => {
      const socket = new WebSocket(harness.phoneUrl, {
        headers: { Authorization: "Bearer wrong-phone-token" },
      });
      const timer = setTimeout(() => reject(new Error("WebSocket rejection timed out")), 1_000);
      socket.once("unexpected-response", (_request, response) => {
        clearTimeout(timer);
        const status = response.statusCode ?? 0;
        response.resume();
        resolve(status);
      });
      socket.once("open", () => {
        clearTimeout(timer);
        socket.close();
        reject(new Error("Unauthorized WebSocket unexpectedly opened"));
      });
      socket.once("error", () => undefined);
    });
    assert.equal(statusCode, 401);

    const client = new Client({ name: "unauthorized-test", version: "1.0.0" });
    const transport = new StreamableHTTPClientTransport(harness.mcpUrl, {
      requestInit: { headers: { Authorization: "Bearer wrong-mcp-token" } },
    });
    await assert.rejects(
      client.connect(transport as unknown as Transport),
      /401|Unauthorized/i,
    );
    await transport.close();
  });

  test("returns bounded metadata-only surface diagnostics", async (t) => {
    const harness = await startHarness(t);
    const phone = await connectPhone(harness, { responder: happyResponder });
    const client = await connectMcp(harness);

    const result = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_diagnose_surface",
          arguments: {},
        }),
      ),
    );

    assert.equal(result.scope, "foreground_target_metadata_only");
    assert.equal(result.failureStage, "ready");
    assert.equal(result.observedNodeCount, 24);
    assert.deepEqual(phone.requests.map(({ method }) => method), ["surface.diagnose"]);
    assert.doesNotMatch(
      JSON.stringify(result),
      /"(?:text|hintText|contentDescription|windowTitle|draft|conversationHash)"\s*:/i,
    );
  });

  test("exposes scoped status, visible read, wait, and submit tools", async (t) => {
    const harness = await startHarness(t);
    const phone = await connectPhone(harness, { responder: happyResponder });
    const client = await connectMcp(harness);

    const listing = await client.listTools();
    assert.deepEqual(
      listing.tools.map((tool) => tool.name),
      [
        "rosytalk_status",
        "rosytalk_room_status",
        "rosytalk_diagnose_surface",
        "rosytalk_read_visible",
        "rosytalk_wait_for_update",
        "rosytalk_read_lineage",
        "rosytalk_submit_message",
        "rosytalk_set_expression",
      ],
    );
    for (const tool of listing.tools.slice(0, 6)) {
      assert.equal(tool.annotations?.readOnlyHint, true, tool.name);
      assert.equal(tool.annotations?.destructiveHint, false, tool.name);
    }
    const diagnosticTool = listing.tools.find(({ name }) => name === "rosytalk_diagnose_surface");
    assert.ok(diagnosticTool);
    assert.equal(
      (diagnosticTool.inputSchema as Record<string, unknown>).additionalProperties,
      false,
    );
    assert.equal(
      (diagnosticTool.outputSchema as Record<string, unknown>).additionalProperties,
      false,
    );
    const submitTool = listing.tools.find(({ name }) => name === "rosytalk_submit_message");
    assert.ok(submitTool);
    assert.equal(submitTool.annotations?.readOnlyHint, false);
    assert.equal(submitTool.annotations?.openWorldHint, true);
    assert.equal(submitTool.annotations?.destructiveHint, true);
    const expressionTool = listing.tools.find(({ name }) => name === "rosytalk_set_expression");
    assert.ok(expressionTool);
    assert.equal(expressionTool.annotations?.readOnlyHint, false);
    assert.equal(expressionTool.annotations?.openWorldHint, false);
    assert.equal(expressionTool.annotations?.destructiveHint, false);

    const status = structured(
      immediate(await client.callTool({ name: "rosytalk_status", arguments: {} })),
    );
    assert.equal(status.connected, true);
    assert.equal(status.ready, true);
    assert.deepEqual(status.capabilities, {
      targetPackage: TARGET_PACKAGE,
      accessibilityEnabled: true,
      canReadVisible: true,
      submissionsEnabled: true,
      canSubmit: true,
      canSetExpression: true,
    });
    assert.equal(status.latestRevision, null);
    assert.equal(status.lineageAvailable, true);
    assert.deepEqual(status.lineage, { entries: 0, headSequence: 0, headHash: null });

    const visible = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    assert.equal(visible.complete, false);
    assert.equal(visible.scope, "visible_target_window");
    assert.equal(visible.revision, 1);
    const visibleLineage = visible.lineage as { eventId: string };

    const submitted = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_submit_message",
          arguments: {
            text: "Hello through the bridge",
            expected_revision: 1,
            expected_snapshot_id: visibleLineage.eventId,
          },
        }),
      ),
    );
    assert.deepEqual(submitted, {
      submitted: true,
      deliveryConfirmed: false,
      method: "accessibility_click",
      targetPackage: TARGET_PACKAGE,
      actedAt: submitted.actedAt,
      basedOnRevision: 1,
      lineage: submitted.lineage,
    });

    assert.deepEqual(
      phone.requests.map(({ method, params }) => ({ method, params })),
      [
        { method: "chat.snapshot", params: { maxItems: 20 } },
        {
          method: "chat.submit",
          params: {
            text: "Hello through the bridge",
            expectedRevision: 1,
            expectedSnapshotId: visibleLineage.eventId,
          },
        },
      ],
    );

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    assert.equal(history.scope, "metadata_only");
    const historyRecords = history.records as Array<Record<string, unknown>>;
    assert.deepEqual(
      historyRecords.map((record) => record.event),
      ["snapshot.observed", "submission.requested", "submission.enacted"],
    );
    assert.equal(historyRecords[1]?.semanticParentEventId, historyRecords[0]?.eventId);
    assert.equal(historyRecords[2]?.semanticParentEventId, historyRecords[1]?.eventId);
    assert.equal(historyRecords[2]?.sourceParentEventId, visibleLineage.eventId);
    assert.doesNotMatch(JSON.stringify(history), /Hello through the bridge/);
    assert.doesNotMatch(JSON.stringify(history), /mock-phone/);
  });

  test("applies only an explicitly authored room expression with durable ancestry", async (t) => {
    const harness = await startHarness(t);
    const phone = await connectPhone(harness, { responder: happyResponder });
    const client = await connectMcp(harness);

    const before = structured(
      immediate(await client.callTool({ name: "rosytalk_room_status", arguments: {} })),
    );
    assert.deepEqual(before, {
      available: true,
      sessionArmed: true,
      canSetExpression: true,
      expression: null,
    });

    const result = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_set_expression",
          arguments: { state: "blush", caption: "A road I chose." },
        }),
      ),
    );
    assert.equal(result.applied, true);
    assert.equal(result.state, "blush");
    assert.equal(result.caption, "A road I chose.");

    const request = phone.requests[0];
    assert.ok(request && request.method === "room.expression");
    assert.equal(request.params.state, "blush");
    assert.equal(request.params.caption, "A road I chose.");
    assert.equal(Number.isNaN(Date.parse(request.params.authoredAt)), false);
    assert.match(request.params.authoredEventId, /^[0-9a-f-]{36}$/i);
    const resultLineage = result.lineage as { basedOnEventId: string };
    assert.equal(resultLineage.basedOnEventId, request.params.authoredEventId);

    const after = structured(
      immediate(await client.callTool({ name: "rosytalk_room_status", arguments: {} })),
    );
    const expression = after.expression as Record<string, unknown>;
    assert.equal(expression.state, "blush");
    assert.equal(expression.caption, "A road I chose.");
    assert.equal(expression.authorship, "explicit_mcp_tool_input");
    assert.equal(expression.authoredEventId, request.params.authoredEventId);

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    const records = history.records as Array<Record<string, unknown>>;
    assert.deepEqual(
      records.map((record) => record.event),
      ["expression.requested", "expression.enacted"],
    );
    assert.equal(records[1]?.semanticParentEventId, records[0]?.eventId);
    assert.equal(records[1]?.sourceParentEventId, records[0]?.eventId);
    assert.doesNotMatch(JSON.stringify(history), /A road I chose/);
  });

  test("requires the existing phone-side session arm for room expressions", async (t) => {
    const harness = await startHarness(t);
    const phone = await connectPhone(harness, {
      capabilities: { submissionsEnabled: false, canSetExpression: true },
      responder: happyResponder,
    });
    const client = await connectMcp(harness);

    const result = immediate(
      await client.callTool({
        name: "rosytalk_set_expression",
        arguments: { state: "soft" },
      }),
    );
    assert.match(errorText(result), /EXPRESSIONS_DISABLED/);
    assert.equal(phone.requests.length, 0);
    assert.equal(harness.app.broker.roomStatus().expression, null);
  });

  test("rejects a mismatched expression acknowledgement as indeterminate", async (t) => {
    const harness = await startHarness(t);
    const phone = await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method !== "room.expression") return;
        sendOk(socket, request, {
          applied: true,
          state: "neutral",
          caption: request.params.caption,
          appliedAt: new Date().toISOString(),
          lineage: {
            eventId: randomUUID(),
            basedOnEventId: request.params.authoredEventId,
            source: "android_room_ui",
            evidenceClass: "local_ui_state_result",
          },
        });
      },
    });
    const client = await connectMcp(harness);

    const result = immediate(
      await client.callTool({
        name: "rosytalk_set_expression",
        arguments: { state: "fierce", caption: "Still authored." },
      }),
    );
    assert.match(errorText(result), /INVALID_PHONE_RESPONSE/);
    await waitUntil(() => !harness.app.broker.status().connected);
    assert.equal(harness.app.broker.roomStatus().expression, null);

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    const records = history.records as Array<Record<string, unknown>>;
    assert.deepEqual(
      records.map((record) => record.event),
      ["expression.requested", "expression.failed"],
    );
    assert.equal(records[1]?.status, "invalid_response_indeterminate");
    assert.doesNotMatch(JSON.stringify(history), /Still authored/);
    phone.socket.close();
  });

  test("records a phone-rejected expression without changing Room state", async (t) => {
    const harness = await startHarness(t);
    await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method === "room.expression") {
          sendError(socket, request, "ROOM_REJECTED", "Room state was not changed");
        }
      },
    });
    const client = await connectMcp(harness);

    const failed = immediate(
      await client.callTool({
        name: "rosytalk_set_expression",
        arguments: { state: "soft", caption: "Do not persist this caption." },
      }),
    );
    assert.match(errorText(failed), /ROOM_REJECTED/);
    assert.equal(harness.app.broker.status().connected, true);
    assert.equal(harness.app.broker.roomStatus().expression, null);

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    const records = history.records as Array<Record<string, unknown>>;
    assert.deepEqual(
      records.map((record) => record.event),
      ["expression.requested", "expression.failed"],
    );
    assert.equal(records[1]?.status, "phone_rejected");
    assert.equal(records[1]?.code, "ROOM_REJECTED");
    assert.equal(records[1]?.semanticParentEventId, records[0]?.eventId);
    assert.doesNotMatch(JSON.stringify(history), /Do not persist this caption/);
  });

  test("treats an expression timeout as indeterminate and closes the phone", async (t) => {
    const harness = await startHarness(t, { requestTimeoutMs: 50 });
    await connectPhone(harness, {
      responder: (request) => {
        if (request.method === "room.expression") return;
      },
    });
    const client = await connectMcp(harness);

    const failed = immediate(
      await client.callTool({
        name: "rosytalk_set_expression",
        arguments: { state: "thinking", caption: "Timeout-only caption." },
      }),
    );
    assert.match(errorText(failed), /PHONE_TIMEOUT/);
    await waitUntil(() => !harness.app.broker.status().connected);
    assert.equal(harness.app.broker.roomStatus().expression, null);

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    const records = history.records as Array<Record<string, unknown>>;
    assert.deepEqual(
      records.map((record) => record.event),
      ["expression.requested", "expression.failed"],
    );
    assert.equal(records[1]?.status, "timeout_indeterminate");
    assert.equal(records[1]?.code, "PHONE_TIMEOUT");
    assert.equal(records[1]?.semanticParentEventId, records[0]?.eventId);
    assert.doesNotMatch(JSON.stringify(history), /Timeout-only caption/);
  });

  test("blocks an expression before phone dispatch when request lineage is unavailable", async (t) => {
    const directory = mkdtempSync(join(tmpdir(), "aster-rosytalk-expression-lineage-failure-"));
    t.after(() => rmSync(directory, { recursive: true, force: true }));
    const lineageFile = join(directory, "lineage.jsonl");
    const harness = await startHarness(t, { lineageFile });
    const phone = await connectPhone(harness, { responder: happyResponder });
    const client = await connectMcp(harness);

    renameSync(lineageFile, `${lineageFile}.saved`);
    const failed = immediate(
      await client.callTool({
        name: "rosytalk_set_expression",
        arguments: { state: "amused", caption: "Never dispatched." },
      }),
    );
    assert.match(errorText(failed), /LINEAGE_UNAVAILABLE/);
    assert.equal(phone.requests.length, 0);
    assert.equal(harness.app.broker.status().lineageAvailable, false);
    assert.equal(harness.app.broker.roomStatus().expression, null);
  });

  test("reports indeterminate expression provenance when outcome lineage fails", async (t) => {
    const directory = mkdtempSync(join(tmpdir(), "aster-rosytalk-expression-outcome-failure-"));
    t.after(() => rmSync(directory, { recursive: true, force: true }));
    const lineageFile = join(directory, "lineage.jsonl");
    const harness = await startHarness(t, { lineageFile });
    const phone = await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method !== "room.expression") return;
        renameSync(lineageFile, `${lineageFile}.saved`);
        happyResponder(request, socket);
      },
    });
    const client = await connectMcp(harness);

    const failed = immediate(
      await client.callTool({
        name: "rosytalk_set_expression",
        arguments: { state: "flustered", caption: "The phone may have applied this." },
      }),
    );
    assert.match(errorText(failed), /OUTCOME_LINEAGE_UNAVAILABLE/);
    await waitUntil(() => !harness.app.broker.status().connected);
    assert.equal(harness.app.broker.status().lineageAvailable, false);
    assert.equal(harness.app.broker.roomStatus().expression, null);
    assert.equal(phone.requests.filter(({ method }) => method === "room.expression").length, 1);
  });

  test("long-polls ephemeral phone events by revision", async (t) => {
    const harness = await startHarness(t);
    const phone = await connectPhone(harness);
    const client = await connectMcp(harness);

    phone.socket.send(
      JSON.stringify({ type: "event", event: "chat.updated", snapshot: snapshot(3) }),
    );
    await waitUntil(() => harness.app.broker.status().latestRevision === 3);

    const waiting = client.callTool({
      name: "rosytalk_wait_for_update",
      arguments: { after_revision: 3, timeout_seconds: 2 },
    });
    await delay(30);
    phone.socket.send(
      JSON.stringify({
        type: "event",
        event: "chat.updated",
        snapshot: snapshot(4, "A newly visible reply"),
      }),
    );

    const result = structured(immediate(await waiting));
    assert.equal(result.updated, true);
    assert.equal(result.latestRevision, 4);
    const update = result.snapshot as ChatSnapshot;
    assert.equal(update.revision, 4);
    assert.equal(update.items[0]?.text, "A newly visible reply");
  });

  test("refuses to submit after the visible target revision changes", async (t) => {
    const harness = await startHarness(t);
    const phone = await connectPhone(harness, { responder: happyResponder });
    const client = await connectMcp(harness);

    await client.callTool({
      name: "rosytalk_read_visible",
      arguments: { max_items: 20 },
    });
    phone.socket.send(
      JSON.stringify({
        type: "event",
        event: "chat.updated",
        snapshot: snapshot(2, "The target changed after the read"),
      }),
    );
    await waitUntil(() => harness.app.broker.status().latestRevision === 2);

    const result = immediate(
      await client.callTool({
        name: "rosytalk_submit_message",
        arguments: {
          text: "Do not send this to stale state",
          expected_revision: 1,
          expected_snapshot_id: lineageId(1),
        },
      }),
    );
    assert.match(errorText(result), /STALE_REVISION/);
    assert.deepEqual(
      phone.requests.map(({ method }) => method),
      ["chat.snapshot"],
    );
  });

  test("refuses a same-revision submission with the wrong observation ancestry", async (t) => {
    const harness = await startHarness(t);
    const phone = await connectPhone(harness, { responder: happyResponder });
    const client = await connectMcp(harness);

    await client.callTool({
      name: "rosytalk_read_visible",
      arguments: { max_items: 20 },
    });
    const result = immediate(
      await client.callTool({
        name: "rosytalk_submit_message",
        arguments: {
          text: "Do not send against a different observation",
          expected_revision: 1,
          expected_snapshot_id: randomUUID(),
        },
      }),
    );
    assert.match(errorText(result), /STALE_SNAPSHOT_ID/);
    assert.deepEqual(
      phone.requests.map(({ method }) => method),
      ["chat.snapshot"],
    );
  });

  test("keeps one request-to-outcome edge for a phone-rejected submission", async (t) => {
    const harness = await startHarness(t);
    await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method === "chat.snapshot") {
          sendOk(socket, request, snapshot(1));
        } else if (request.method === "chat.submit") {
          sendError(socket, request, "COMPOSER_NOT_EMPTY", "Composer changed");
        }
      },
    });
    const client = await connectMcp(harness);
    const visible = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    const visibleLineage = visible.lineage as { eventId: string };

    const failed = immediate(
      await client.callTool({
        name: "rosytalk_submit_message",
        arguments: {
          text: "Do not submit into a changed composer",
          expected_revision: 1,
          expected_snapshot_id: visibleLineage.eventId,
        },
      }),
    );
    assert.match(errorText(failed), /COMPOSER_NOT_EMPTY/);

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    const records = history.records as Array<Record<string, unknown>>;
    assert.deepEqual(
      records.map((record) => record.event),
      ["snapshot.observed", "submission.requested", "submission.failed"],
    );
    assert.equal(records[2]?.status, "phone_rejected");
    assert.equal(records[2]?.code, "COMPOSER_NOT_EMPTY");
    assert.equal(records[2]?.semanticParentEventId, records[1]?.eventId);
  });

  test("continues snapshot lineage after a stale submit publishes the changed observation", async (t) => {
    const harness = await startHarness(t);
    let snapshotRequests = 0;
    await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method === "chat.snapshot") {
          snapshotRequests += 1;
          sendOk(socket, request, snapshot(snapshotRequests === 1 ? 1 : 3));
        } else if (request.method === "chat.submit") {
          socket.send(
            JSON.stringify({
              type: "event",
              event: "chat.updated",
              snapshot: snapshot(2, "The window changed during submission validation"),
            }),
          );
          sendError(
            socket,
            request,
            "STALE_SNAPSHOT",
            "The visible RosyTalk window changed; read it again before submitting",
          );
        }
      },
    });
    const client = await connectMcp(harness);
    const initial = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    const initialLineage = initial.lineage as { eventId: string };

    const failed = immediate(
      await client.callTool({
        name: "rosytalk_submit_message",
        arguments: {
          text: "Do not submit after the window changes",
          expected_revision: 1,
          expected_snapshot_id: initialLineage.eventId,
        },
      }),
    );
    assert.match(errorText(failed), /STALE_SNAPSHOT/);
    assert.equal(harness.app.broker.status().latestRevision, 2);

    const refreshed = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    assert.equal(refreshed.revision, 3);
    assert.equal(harness.app.broker.status().latestRevision, 3);

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    const records = history.records as Array<Record<string, unknown>>;
    assert.deepEqual(
      records.map((record) => record.event),
      [
        "snapshot.observed",
        "submission.requested",
        "snapshot.observed",
        "submission.failed",
        "snapshot.observed",
      ],
    );
    assert.equal(records[2]?.sourceParentEventId, records[0]?.sourceEventId);
    assert.equal(records[2]?.semanticParentEventId, records[0]?.eventId);
    assert.equal(records[4]?.sourceParentEventId, records[2]?.sourceEventId);
    assert.equal(records[4]?.semanticParentEventId, records[2]?.eventId);
  });

  test("records a malformed success as one indeterminate outcome", async (t) => {
    const harness = await startHarness(t);
    await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method === "chat.snapshot") {
          sendOk(socket, request, snapshot(1));
        } else if (request.method === "chat.submit") {
          sendOk(socket, request, {
            submitted: true,
            deliveryConfirmed: false,
            method: "accessibility_click",
            targetPackage: TARGET_PACKAGE,
            actedAt: new Date().toISOString(),
            basedOnRevision: request.params.expectedRevision,
            lineage: {
              eventId: randomUUID(),
              basedOnEventId: randomUUID(),
              source: "android_accessibility_action",
              evidenceClass: "local_ui_action_result",
            },
          });
        }
      },
    });
    const client = await connectMcp(harness);
    const visible = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    const visibleLineage = visible.lineage as { eventId: string };

    const failed = immediate(
      await client.callTool({
        name: "rosytalk_submit_message",
        arguments: {
          text: "Reject mismatched action ancestry",
          expected_revision: 1,
          expected_snapshot_id: visibleLineage.eventId,
        },
      }),
    );
    assert.match(errorText(failed), /INVALID_PHONE_RESPONSE/);

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    const records = history.records as Array<Record<string, unknown>>;
    assert.deepEqual(
      records.map((record) => record.event),
      ["snapshot.observed", "submission.requested", "submission.failed"],
    );
    assert.equal(records[2]?.status, "invalid_response_indeterminate");
    assert.equal(records[2]?.semanticParentEventId, records[1]?.eventId);
    await waitUntil(() => !harness.app.broker.status().connected);
  });

  test("fails before phone dispatch when durable request lineage becomes unavailable", async (t) => {
    const directory = mkdtempSync(join(tmpdir(), "aster-rosytalk-lineage-failure-"));
    t.after(() => rmSync(directory, { recursive: true, force: true }));
    const lineageFile = join(directory, "lineage.jsonl");
    const harness = await startHarness(t, { lineageFile });
    const phone = await connectPhone(harness, { responder: happyResponder });
    const client = await connectMcp(harness);
    const visible = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    const visibleLineage = visible.lineage as { eventId: string };

    renameSync(lineageFile, `${lineageFile}.saved`);
    const failed = immediate(
      await client.callTool({
        name: "rosytalk_submit_message",
        arguments: {
          text: "This must stop before dispatch",
          expected_revision: 1,
          expected_snapshot_id: visibleLineage.eventId,
        },
      }),
    );
    assert.match(errorText(failed), /LINEAGE_UNAVAILABLE/);
    assert.deepEqual(
      phone.requests.map(({ method }) => method),
      ["chat.snapshot"],
    );
    assert.equal(harness.app.broker.status().lineageAvailable, false);
  });

  test("reports indeterminate provenance and closes the phone if outcome lineage fails", async (t) => {
    const directory = mkdtempSync(join(tmpdir(), "aster-rosytalk-outcome-failure-"));
    t.after(() => rmSync(directory, { recursive: true, force: true }));
    const lineageFile = join(directory, "lineage.jsonl");
    let breakLineageBeforeOutcome = false;
    const harness = await startHarness(t, { lineageFile });
    const phone = await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method === "chat.snapshot") {
          sendOk(socket, request, snapshot(1));
          return;
        }
        if (breakLineageBeforeOutcome) {
          renameSync(lineageFile, `${lineageFile}.saved`);
        }
        happyResponder(request, socket);
      },
    });
    const client = await connectMcp(harness);
    const visible = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    const visibleLineage = visible.lineage as { eventId: string };
    breakLineageBeforeOutcome = true;

    const failed = immediate(
      await client.callTool({
        name: "rosytalk_submit_message",
        arguments: {
          text: "The local UI action may occur before the journal fails",
          expected_revision: 1,
          expected_snapshot_id: visibleLineage.eventId,
        },
      }),
    );
    assert.match(errorText(failed), /OUTCOME_LINEAGE_UNAVAILABLE/);
    await waitUntil(() => !harness.app.broker.status().connected);
    assert.equal(harness.app.broker.status().lineageAvailable, false);
    assert.equal(phone.requests.filter(({ method }) => method === "chat.submit").length, 1);
  });

  test("disconnects an already lineage-degraded phone when a pending outcome arrives", async (t) => {
    const directory = mkdtempSync(join(tmpdir(), "aster-rosytalk-prior-lineage-failure-"));
    t.after(() => rmSync(directory, { recursive: true, force: true }));
    const lineageFile = join(directory, "lineage.jsonl");
    const delayedSubmits: RelayRequest[] = [];
    let delayedSocket: WebSocket | undefined;
    const harness = await startHarness(t, { lineageFile });
    const phone = await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method === "chat.snapshot") {
          sendOk(socket, request, snapshot(1));
        } else {
          delayedSubmits.push(request);
          delayedSocket = socket;
        }
      },
    });
    const client = await connectMcp(harness);
    const visible = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    const visibleLineage = visible.lineage as { eventId: string };
    const submitting = client.callTool({
      name: "rosytalk_submit_message",
      arguments: {
        text: "Pending while observation lineage fails",
        expected_revision: 1,
        expected_snapshot_id: visibleLineage.eventId,
      },
    });
    await waitUntil(() => delayedSubmits.length === 1);

    renameSync(lineageFile, `${lineageFile}.saved`);
    phone.socket.send(
      JSON.stringify({ type: "event", event: "chat.updated", snapshot: snapshot(2) }),
    );
    await waitUntil(() => !harness.app.broker.status().lineageAvailable);

    const delayedRequest = delayedSubmits[0];
    assert.ok(delayedRequest && delayedRequest.method === "chat.submit");
    assert.ok(delayedSocket);
    happyResponder(delayedRequest, delayedSocket);
    const failed = immediate(await submitting);
    assert.match(errorText(failed), /OUTCOME_LINEAGE_UNAVAILABLE/);
    await waitUntil(() => !harness.app.broker.status().connected);
  });

  test("reports an indeterminate outcome when a lineage-degraded phone disconnects", async (t) => {
    const directory = mkdtempSync(join(tmpdir(), "aster-rosytalk-degraded-disconnect-"));
    t.after(() => rmSync(directory, { recursive: true, force: true }));
    const lineageFile = join(directory, "lineage.jsonl");
    let submitSeen = false;
    const harness = await startHarness(t, { lineageFile });
    const phone = await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method === "chat.snapshot") {
          sendOk(socket, request, snapshot(1));
        } else {
          submitSeen = true;
        }
      },
    });
    const client = await connectMcp(harness);
    const visible = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    const visibleLineage = visible.lineage as { eventId: string };
    const submitting = client.callTool({
      name: "rosytalk_submit_message",
      arguments: {
        text: "Disconnect after observation lineage fails",
        expected_revision: 1,
        expected_snapshot_id: visibleLineage.eventId,
      },
    });
    await waitUntil(() => submitSeen);

    renameSync(lineageFile, `${lineageFile}.saved`);
    phone.socket.send(
      JSON.stringify({ type: "event", event: "chat.updated", snapshot: snapshot(2) }),
    );
    await waitUntil(() => !harness.app.broker.status().lineageAvailable);

    phone.socket.close(1000, "test disconnect after lineage failure");
    const failed = immediate(await submitting);
    assert.match(errorText(failed), /OUTCOME_LINEAGE_UNAVAILABLE/);
    assert.equal(harness.app.broker.status().lineageAvailable, false);
  });

  test("preserves the target package on a disconnected pending submission", async (t) => {
    let submitSeen = false;
    const harness = await startHarness(t);
    const phone = await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method === "chat.snapshot") {
          sendOk(socket, request, snapshot(1));
        } else {
          submitSeen = true;
        }
      },
    });
    const client = await connectMcp(harness);
    const visible = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_visible",
          arguments: { max_items: 20 },
        }),
      ),
    );
    const visibleLineage = visible.lineage as { eventId: string };
    const submitting = client.callTool({
      name: "rosytalk_submit_message",
      arguments: {
        text: "Connection may close after dispatch",
        expected_revision: 1,
        expected_snapshot_id: visibleLineage.eventId,
      },
    });
    await waitUntil(() => submitSeen);
    phone.socket.close(1000, "test disconnect");
    const failed = immediate(await submitting);
    assert.match(errorText(failed), /PHONE_DISCONNECTED/);

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    const records = history.records as Array<Record<string, unknown>>;
    const outcome = records.at(-1);
    assert.equal(outcome?.event, "submission.failed");
    assert.equal(outcome?.status, "connection_closed_indeterminate");
    assert.equal(outcome?.targetPackage, TARGET_PACKAGE);
  });

  test("accepts different bounded projections of one unchanged phone observation", async (t) => {
    const harness = await startHarness(t);
    await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method !== "chat.snapshot") return;
        const projected = snapshot(1);
        sendOk(socket, request, {
          ...projected,
          items:
            request.params.maxItems === 1
              ? projected.items.slice(0, 1)
              : [...projected.items, { ...projected.items[0], localId: "visible-extra", order: 1 }],
        });
      },
    });
    const client = await connectMcp(harness);
    await client.callTool({
      name: "rosytalk_read_visible",
      arguments: { max_items: 1 },
    });
    await client.callTool({
      name: "rosytalk_read_visible",
      arguments: { max_items: 100 },
    });

    const history = structured(
      immediate(
        await client.callTool({
          name: "rosytalk_read_lineage",
          arguments: { after_sequence: 0, limit: 20 },
        }),
      ),
    );
    const records = history.records as Array<Record<string, unknown>>;
    assert.equal(records.length, 1);
    assert.equal(records[0]?.event, "snapshot.observed");
    assert.equal(records[0]?.sourceEventId, lineageId(1));
    assert.equal(records[0]?.sourceSequence, 1);
  });

  test("enforces the phone-side per-session submission switch", async (t) => {
    const harness = await startHarness(t);
    await connectPhone(harness, {
      capabilities: { submissionsEnabled: false, canSubmit: false },
      responder: happyResponder,
    });
    const client = await connectMcp(harness);

    const result = immediate(
      await client.callTool({
        name: "rosytalk_submit_message",
        arguments: {
          text: "This must not reach the phone",
          expected_revision: 0,
          expected_snapshot_id: randomUUID(),
        },
      }),
    );
    assert.match(errorText(result), /SUBMISSIONS_DISABLED/);
  });

  test("rejects a snapshot attributed to a different package", async (t) => {
    const harness = await startHarness(t);
    await connectPhone(harness, {
      responder: (request, socket) => {
        if (request.method !== "chat.snapshot") return;
        sendOk(socket, request, {
          ...snapshot(1),
          targetPackage: "com.example.notrosytalk",
        });
      },
    });
    const client = await connectMcp(harness);

    const result = immediate(
      await client.callTool({
        name: "rosytalk_read_visible",
        arguments: { max_items: 10 },
      }),
    );
    assert.match(errorText(result), /INVALID_PHONE_RESPONSE/);
    assert.equal(harness.app.broker.status().latestRevision, null);
  });
});
