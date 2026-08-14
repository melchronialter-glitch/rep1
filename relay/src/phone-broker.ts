import { randomUUID } from "node:crypto";
import WebSocket from "ws";
import { audit } from "./audit.js";
import type {
  LineageAppend,
  LineageStore,
  StoredLineageRecord,
} from "./lineage.js";
import {
  type AuthoredExpressionStatus,
  type ChatSnapshot,
  type PhoneHello,
  type RelayMethod,
  type RelayRequest,
  type RoomExpressionInput,
  type RoomExpressionResult,
  chatUpdatedEventSchema,
  parseResult,
  phoneHelloSchema,
  phoneResponseSchema,
  relayRequestSchema,
  roomExpressionInputSchema,
} from "./protocol.js";

const MAX_PENDING_REQUESTS = 1;
const MAX_UPDATE_WAITERS = 8;

export class RosyTalkBridgeError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "RosyTalkBridgeError";
  }
}

interface PendingRequest {
  method: RelayMethod;
  startedAt: number;
  timeout: NodeJS.Timeout;
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  requestLineageEventId: string | null;
  expectedSnapshotId: string | null;
  expectedRevision: number | null;
  expectedExpression: ExpectedExpression | null;
}

interface ExpectedExpression {
  state: RoomExpressionInput["state"];
  caption: string | null;
  authoredAt: string;
  authoredEventId: string;
}

interface UpdateWaiter {
  afterRevision: number;
  timeout: NodeJS.Timeout;
  resolve: (snapshot: ChatSnapshot | null) => void;
  reject: (error: Error) => void;
}

export interface BrokerStatus {
  connected: boolean;
  ready: boolean;
  connectedAt: string | null;
  device: PhoneHello["device"] | null;
  capabilities: PhoneHello["capabilities"] | null;
  pendingRequests: number;
  latestRevision: number | null;
  lastUpdateAt: string | null;
  lineageAvailable: boolean;
}

export interface RoomStatus {
  available: boolean;
  sessionArmed: boolean;
  canSetExpression: boolean;
  expression: AuthoredExpressionStatus | null;
}

export class PhoneBroker {
  private socket: WebSocket | undefined;
  private hello: PhoneHello | undefined;
  private connectedAt: Date | undefined;
  private helloTimer: NodeJS.Timeout | undefined;
  private latestSnapshot: ChatSnapshot | undefined;
  private expression: AuthoredExpressionStatus | undefined;
  private lineageFailure: string | undefined;
  private readonly pending = new Map<string, PendingRequest>();
  private readonly updateWaiters = new Set<UpdateWaiter>();

  constructor(
    private readonly requestTimeoutMs: number,
    private readonly lineage: LineageStore,
  ) {}

  attach(socket: WebSocket): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.close(4001, "Replaced by a newly authorized phone connection");
    }
    this.rejectAll(new RosyTalkBridgeError("PHONE_REPLACED", "Phone connection replaced"));
    this.rejectWaiters(
      new RosyTalkBridgeError("PHONE_REPLACED", "Phone connection replaced"),
    );
    this.socket = socket;
    this.hello = undefined;
    this.latestSnapshot = undefined;
    this.expression = undefined;
    this.connectedAt = new Date();

    this.helloTimer = setTimeout(() => {
      if (!this.hello && this.socket === socket) {
        socket.close(4002, "Hello message required");
      }
    }, 5_000);

    socket.on("message", (raw) => this.onMessage(socket, raw.toString()));
    socket.on("close", () => this.onClose(socket));
    socket.on("error", (error) => {
      audit({ event: "chat.error", code: "PHONE_SOCKET", detail: error.message });
    });
  }

  status(): BrokerStatus {
    const connected = this.socket?.readyState === WebSocket.OPEN;
    return {
      connected,
      ready: connected && this.hello !== undefined,
      connectedAt: this.connectedAt?.toISOString() ?? null,
      device: this.hello?.device ?? null,
      capabilities: this.hello?.capabilities ?? null,
      pendingRequests: this.pending.size,
      latestRevision: this.latestSnapshot?.revision ?? null,
      lastUpdateAt: this.latestSnapshot?.capturedAt ?? null,
      lineageAvailable: this.lineageFailure === undefined,
    };
  }

  currentSnapshot(): ChatSnapshot | null {
    return this.latestSnapshot ?? null;
  }

  roomStatus(): RoomStatus {
    const status = this.status();
    return {
      available: status.ready && status.capabilities?.canSetExpression === true,
      sessionArmed: status.capabilities?.submissionsEnabled === true,
      canSetExpression: status.capabilities?.canSetExpression === true,
      expression: this.expression ?? null,
    };
  }

  async request(
    method: RelayMethod,
    params: Record<string, unknown>,
    timeoutMs = this.requestTimeoutMs,
  ): Promise<unknown> {
    const socket = this.socket;
    const hello = this.hello;
    if (!socket || socket.readyState !== WebSocket.OPEN || !hello) {
      throw new RosyTalkBridgeError(
        "PHONE_OFFLINE",
        "The Android RosyTalk Bridge is not connected and ready",
      );
    }
    if (method === "chat.snapshot" || method === "chat.submit") {
      if (!hello.capabilities.targetPackage) {
        throw new RosyTalkBridgeError(
          "TARGET_NOT_CONFIGURED",
          "Select the exact RosyTalk app in the Android bridge",
        );
      }
      if (!hello.capabilities.accessibilityEnabled) {
        throw new RosyTalkBridgeError(
          "ACCESSIBILITY_DISABLED",
          "Enable the RosyTalk Bridge accessibility service on the phone",
        );
      }
    }
    if (method === "chat.snapshot" && !hello.capabilities.canReadVisible) {
      throw new RosyTalkBridgeError(
        "READ_UNAVAILABLE",
        "The phone cannot currently read the visible target window",
      );
    }
    if (
      method === "chat.submit" &&
      (!hello.capabilities.submissionsEnabled || !hello.capabilities.canSubmit)
    ) {
      throw new RosyTalkBridgeError(
        "SUBMISSIONS_DISABLED",
        "Enable message submission for this session in the Android bridge",
      );
    }
    if (
      method === "room.expression" &&
      (!hello.capabilities.submissionsEnabled || !hello.capabilities.canSetExpression)
    ) {
      throw new RosyTalkBridgeError(
        "EXPRESSIONS_DISABLED",
        "Arm this bridge session and enable authored expressions on the phone",
      );
    }
    if ((method === "chat.submit" || method === "room.expression") && this.lineageFailure) {
      throw new RosyTalkBridgeError(
        "LINEAGE_UNAVAILABLE",
        "The action is blocked because durable lineage is unavailable; restart after repairing storage",
      );
    }
    if (this.pending.size >= MAX_PENDING_REQUESTS) {
      audit({ event: "chat.error", method, code: "PHONE_BUSY" });
      throw new RosyTalkBridgeError(
        "PHONE_BUSY",
        "The phone is already handling another RosyTalk request",
      );
    }

    const id = randomUUID();
    let requestLineageEventId: string | null = null;
    let expectedExpression: ExpectedExpression | null = null;
    let wireParams = params;
    if (method === "room.expression") {
      const input = roomExpressionInputSchema.parse(params);
      const requested = this.appendLineage({
        event: "expression.requested",
        source: "mcp_client",
        evidenceClass: "relay_observed_request",
        requestId: id,
        method: "room.expression",
        status: "requested",
      });
      requestLineageEventId = requested.eventId;
      expectedExpression = {
        state: input.state,
        caption: input.caption ?? null,
        authoredAt: requested.recordedAt,
        authoredEventId: requested.eventId,
      };
      wireParams = { ...expectedExpression };
    }
    const request = relayRequestSchema.parse({ type: "request", id, method, params: wireParams });
    if (request.method === "chat.submit") {
      const currentRevision = this.latestSnapshot?.revision;
      if (currentRevision === undefined) {
        throw new RosyTalkBridgeError(
          "VISIBLE_REVISION_REQUIRED",
          "Read the visible target window before submitting a message",
        );
      }
      if (request.params.expectedRevision !== currentRevision) {
        audit({ event: "chat.error", method, code: "STALE_REVISION" });
        throw new RosyTalkBridgeError(
          "STALE_REVISION",
          "The visible target window changed; read it again before submitting",
        );
      }
      const currentSnapshotId = this.latestSnapshot?.lineage.eventId;
      if (request.params.expectedSnapshotId !== currentSnapshotId) {
        audit({ event: "chat.error", method, code: "STALE_SNAPSHOT_ID" });
        throw new RosyTalkBridgeError(
          "STALE_SNAPSHOT_ID",
          "The visible snapshot ancestry changed; read it again before submitting",
        );
      }
    }
    audit({ event: "chat.request", requestId: id, method, deviceId: hello.device.id });
    if (request.method === "chat.submit") {
      const observation = this.lineage.findBySourceEventId(
        request.params.expectedSnapshotId,
      );
      if (!observation) {
        throw new RosyTalkBridgeError(
          "LINEAGE_UNAVAILABLE",
          "The current visible observation has no durable lineage record",
        );
      }
      const requested = this.appendLineage({
        event: "submission.requested",
        source: "mcp_client",
        evidenceClass: "relay_observed_request",
        semanticParentEventId: observation.eventId,
        requestId: id,
        targetPackage: hello.capabilities.targetPackage,
        revision: request.params.expectedRevision,
        status: "requested",
      });
      requestLineageEventId = requested.eventId;
    }

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        audit({ event: "chat.error", requestId: id, method, code: "TIMEOUT" });
        if (method === "chat.submit") {
          let timeoutError: Error = new RosyTalkBridgeError(
            "PHONE_TIMEOUT",
            `The phone did not answer ${method} within ${timeoutMs} ms`,
          );
          try {
            this.appendLineage({
              event: "submission.failed",
              source: "relay",
              evidenceClass: "relay_observed_outcome",
              semanticParentEventId: requestLineageEventId,
              requestId: id,
              targetPackage: hello.capabilities.targetPackage,
              status: "timeout_indeterminate",
              code: "PHONE_TIMEOUT",
            }, true);
          } catch (error) {
            if (error instanceof Error) timeoutError = error;
          }
          this.socket?.close(4011, "Indeterminate submission outcome");
          reject(timeoutError);
          return;
        }
        if (method === "room.expression") {
          let timeoutError: Error = new RosyTalkBridgeError(
            "PHONE_TIMEOUT",
            `The phone did not answer ${method} within ${timeoutMs} ms`,
          );
          try {
            this.appendLineage({
              event: "expression.failed",
              source: "relay",
              evidenceClass: "relay_observed_outcome",
              semanticParentEventId: requestLineageEventId,
              requestId: id,
              method: "room.expression",
              status: "timeout_indeterminate",
              code: "PHONE_TIMEOUT",
            }, true);
          } catch (error) {
            if (error instanceof Error) timeoutError = error;
          }
          this.socket?.close(4011, "Indeterminate expression outcome");
          reject(timeoutError);
          return;
        }
        reject(
          new RosyTalkBridgeError(
            "PHONE_TIMEOUT",
            `The phone did not answer ${method} within ${timeoutMs} ms`,
          ),
        );
      }, timeoutMs);

      this.pending.set(id, {
        method,
        startedAt: Date.now(),
        timeout,
        resolve,
        reject,
        requestLineageEventId,
        expectedSnapshotId:
          request.method === "chat.submit" ? request.params.expectedSnapshotId : null,
        expectedRevision:
          request.method === "chat.submit" ? request.params.expectedRevision : null,
        expectedExpression,
      });

      socket.send(JSON.stringify(request), (error) => {
        if (!error) return;
        const pending = this.pending.get(id);
        if (!pending) return;
        clearTimeout(pending.timeout);
        this.pending.delete(id);
        let sendError: Error = new RosyTalkBridgeError("PHONE_SEND_FAILED", error.message);
        if (method === "chat.submit") {
          try {
            this.appendLineage({
              event: "submission.failed",
              source: "relay",
              evidenceClass: "relay_observed_outcome",
              semanticParentEventId: requestLineageEventId,
              requestId: id,
              targetPackage: hello.capabilities.targetPackage,
              status: "transport_send_failed",
              code: "PHONE_SEND_FAILED",
            }, true);
          } catch (lineageError) {
            if (lineageError instanceof Error) sendError = lineageError;
          }
        }
        if (method === "room.expression") {
          try {
            this.appendLineage({
              event: "expression.failed",
              source: "relay",
              evidenceClass: "relay_observed_outcome",
              semanticParentEventId: requestLineageEventId,
              requestId: id,
              method: "room.expression",
              status: "transport_send_failed",
              code: "PHONE_SEND_FAILED",
            }, true);
          } catch (lineageError) {
            if (lineageError instanceof Error) sendError = lineageError;
          }
        }
        reject(sendError);
      });
    });
  }

  waitForUpdate(afterRevision: number | undefined, timeoutMs: number): Promise<ChatSnapshot | null> {
    const hello = this.hello;
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN || !hello) {
      return Promise.reject(
        new RosyTalkBridgeError("PHONE_OFFLINE", "The Android RosyTalk Bridge is offline"),
      );
    }
    if (!hello.capabilities.accessibilityEnabled || !hello.capabilities.canReadVisible) {
      return Promise.reject(
        new RosyTalkBridgeError(
          "READ_UNAVAILABLE",
          "The phone cannot currently read the visible target window",
        ),
      );
    }
    if (this.updateWaiters.size >= MAX_UPDATE_WAITERS) {
      return Promise.reject(
        new RosyTalkBridgeError("TOO_MANY_WAITERS", "Too many update waits are active"),
      );
    }

    const baseline = afterRevision ?? this.latestSnapshot?.revision ?? -1;
    if (this.latestSnapshot && this.latestSnapshot.revision > baseline) {
      return Promise.resolve(this.latestSnapshot);
    }

    return new Promise((resolve, reject) => {
      const waiter: UpdateWaiter = {
        afterRevision: baseline,
        timeout: setTimeout(() => {
          this.updateWaiters.delete(waiter);
          resolve(null);
        }, timeoutMs),
        resolve,
        reject,
      };
      this.updateWaiters.add(waiter);
    });
  }

  close(): void {
    if (this.helloTimer) clearTimeout(this.helloTimer);
    this.rejectAll(new RosyTalkBridgeError("RELAY_STOPPED", "Relay stopped"));
    this.rejectWaiters(new RosyTalkBridgeError("RELAY_STOPPED", "Relay stopped"));
    this.socket?.close(1001, "Relay stopped");
    this.socket = undefined;
    this.hello = undefined;
    this.latestSnapshot = undefined;
    this.expression = undefined;
    this.connectedAt = undefined;
  }

  private appendLineage(
    input: LineageAppend,
    actionMayHaveOccurred = false,
  ): StoredLineageRecord {
    if (this.lineageFailure) {
      if (actionMayHaveOccurred) {
        this.socket?.close(4010, "Durable outcome lineage unavailable");
      }
      throw new RosyTalkBridgeError(
        actionMayHaveOccurred ? "OUTCOME_LINEAGE_UNAVAILABLE" : "LINEAGE_UNAVAILABLE",
        actionMayHaveOccurred
          ? "The phone action may have occurred, but its durable outcome lineage is unavailable"
          : "Durable bridge lineage is unavailable",
      );
    }
    try {
      return this.lineage.append(input);
    } catch (error) {
      this.lineageFailure = error instanceof Error ? error.message : "unknown lineage failure";
      audit({ event: "chat.error", code: "LINEAGE_UNAVAILABLE" });
      if (actionMayHaveOccurred) {
        this.socket?.close(4010, "Durable outcome lineage unavailable");
      }
      throw new RosyTalkBridgeError(
        actionMayHaveOccurred ? "OUTCOME_LINEAGE_UNAVAILABLE" : "LINEAGE_UNAVAILABLE",
        actionMayHaveOccurred
          ? "The phone action may have occurred, but its durable outcome lineage could not be recorded"
          : "Durable bridge lineage could not be recorded",
      );
    }
  }

  private onMessage(socket: WebSocket, raw: string): void {
    if (socket !== this.socket) return;
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch {
      socket.close(4003, "Invalid JSON");
      return;
    }

    if (!this.hello) {
      const hello = phoneHelloSchema.safeParse(value);
      if (!hello.success) {
        socket.close(4004, "Invalid hello message");
        return;
      }
      this.hello = hello.data;
      if (this.helloTimer) clearTimeout(this.helloTimer);
      audit({ event: "phone.connected", deviceId: hello.data.device.id });
      return;
    }

    const event = chatUpdatedEventSchema.safeParse(value);
    if (event.success) {
      try {
        this.acceptSnapshot(event.data.snapshot);
      } catch {
        audit({ event: "chat.error", code: "INVALID_PHONE_EVENT" });
      }
      return;
    }

    const parsed = phoneResponseSchema.safeParse(value);
    if (!parsed.success) {
      audit({ event: "chat.error", code: "INVALID_PHONE_RESPONSE" });
      return;
    }

    const response = parsed.data;
    const pending = this.pending.get(response.id);
    if (!pending) return;
    this.pending.delete(response.id);
    clearTimeout(pending.timeout);
    const durationMs = Date.now() - pending.startedAt;

    if (!response.ok) {
      audit({
        event: "chat.error",
        requestId: response.id,
        method: pending.method,
        durationMs,
        code: response.error.code,
      });
      let rejection: Error = new RosyTalkBridgeError(
        response.error.code,
        response.error.message,
      );
      if (pending.method === "chat.submit") {
        try {
          this.appendLineage({
            event: "submission.failed",
            source: "relay",
            evidenceClass: "relay_observed_outcome",
            semanticParentEventId: pending.requestLineageEventId,
            requestId: response.id,
            targetPackage: this.hello?.capabilities.targetPackage ?? null,
            status: "phone_rejected",
            code: response.error.code,
          }, true);
        } catch (error) {
          if (error instanceof Error) rejection = error;
        }
      }
      if (pending.method === "room.expression") {
        try {
          this.appendLineage({
            event: "expression.failed",
            source: "relay",
            evidenceClass: "relay_observed_outcome",
            semanticParentEventId: pending.requestLineageEventId,
            requestId: response.id,
            method: "room.expression",
            status: "phone_rejected",
            code: response.error.code,
          }, true);
        } catch (error) {
          if (error instanceof Error) rejection = error;
        }
      }
      pending.reject(rejection);
      return;
    }

    try {
      const result = parseResult(pending.method, response.result);
      if (pending.method === "chat.snapshot" || pending.method === "chat.submit") {
        this.assertTargetPackage(
          (result as ChatSnapshot | import("./protocol.js").SubmitResult).targetPackage,
        );
      }
      if (pending.method === "chat.snapshot") {
        this.acceptSnapshot(result as ChatSnapshot);
      } else if (pending.method === "chat.submit") {
        const submit = result as import("./protocol.js").SubmitResult;
        if (
          submit.lineage.basedOnEventId !== pending.expectedSnapshotId ||
          submit.basedOnRevision !== pending.expectedRevision
        ) {
          throw new Error("Phone action result did not match the requested ancestry");
        }
        this.appendLineage({
          event: "submission.enacted",
          source: "android_bridge",
          evidenceClass: "authenticated_phone_report",
          sourceEventId: submit.lineage.eventId,
          sourceParentEventId: submit.lineage.basedOnEventId,
          semanticParentEventId: pending.requestLineageEventId,
          requestId: response.id,
          targetPackage: submit.targetPackage,
          revision: submit.basedOnRevision,
          method: submit.method,
          status: "local_ui_action_only",
        }, true);
      } else {
        const expression = result as RoomExpressionResult;
        const expected = pending.expectedExpression;
        if (
          !expected ||
          expression.state !== expected.state ||
          expression.caption !== expected.caption ||
          expression.lineage.basedOnEventId !== expected.authoredEventId
        ) {
          throw new Error("Phone expression result did not match the authored request");
        }
        this.appendLineage({
          event: "expression.enacted",
          source: "android_bridge",
          evidenceClass: "authenticated_phone_report",
          sourceEventId: expression.lineage.eventId,
          sourceParentEventId: expression.lineage.basedOnEventId,
          semanticParentEventId: pending.requestLineageEventId,
          requestId: response.id,
          method: "room.expression",
          status: "local_ui_state_only",
        }, true);
        this.expression = {
          state: expression.state,
          caption: expression.caption,
          authoredAt: expected.authoredAt,
          authoredEventId: expected.authoredEventId,
          appliedAt: expression.appliedAt,
          lineage: expression.lineage,
          authorship: "explicit_mcp_tool_input",
        };
      }
      audit({
        event: "chat.response",
        requestId: response.id,
        method: pending.method,
        durationMs,
      });
      pending.resolve(result);
    } catch (error) {
      const responseCode =
        error instanceof RosyTalkBridgeError ? error.code : "INVALID_PHONE_RESPONSE";
      audit({
        event: "chat.error",
        requestId: response.id,
        method: pending.method,
        durationMs,
        code: responseCode,
      });
      let rejection: Error =
        error instanceof RosyTalkBridgeError
          ? error
          : new RosyTalkBridgeError(
              "INVALID_PHONE_RESPONSE",
              `Phone returned an invalid result for ${pending.method}`,
            );
      if (pending.method === "chat.submit" && !(error instanceof RosyTalkBridgeError)) {
        try {
          this.appendLineage({
            event: "submission.failed",
            source: "relay",
            evidenceClass: "relay_observed_outcome",
            semanticParentEventId: pending.requestLineageEventId,
            requestId: response.id,
            targetPackage: this.hello?.capabilities.targetPackage ?? null,
            status: "invalid_response_indeterminate",
            code: "INVALID_PHONE_RESPONSE",
          }, true);
        } catch (lineageError) {
          if (lineageError instanceof Error) rejection = lineageError;
        }
        this.socket?.close(4011, "Indeterminate submission outcome");
      }
      if (pending.method === "room.expression" && !(error instanceof RosyTalkBridgeError)) {
        try {
          this.appendLineage({
            event: "expression.failed",
            source: "relay",
            evidenceClass: "relay_observed_outcome",
            semanticParentEventId: pending.requestLineageEventId,
            requestId: response.id,
            method: "room.expression",
            status: "invalid_response_indeterminate",
            code: "INVALID_PHONE_RESPONSE",
          }, true);
        } catch (lineageError) {
          if (lineageError instanceof Error) rejection = lineageError;
        }
        this.socket?.close(4011, "Indeterminate expression outcome");
      }
      pending.reject(rejection);
    }
  }

  private acceptSnapshot(snapshot: ChatSnapshot): void {
    this.assertTargetPackage(snapshot.targetPackage);
    const previousRevision = this.latestSnapshot?.revision;
    if (previousRevision !== undefined && snapshot.revision < previousRevision) {
      throw new Error("Snapshot revision moved backwards");
    }
    if (
      this.latestSnapshot &&
      snapshot.revision === previousRevision &&
      snapshot.lineage.eventId !== this.latestSnapshot.lineage.eventId
    ) {
      throw new Error("Snapshot identity changed without a new revision");
    }
    if (
      this.latestSnapshot &&
      snapshot.revision > (previousRevision ?? -1) &&
      snapshot.lineage.parentEventId !== this.latestSnapshot.lineage.eventId
    ) {
      throw new Error("Snapshot lineage did not descend from the current observation");
    }
    this.appendLineage({
      event: "snapshot.observed",
      source: "android_bridge",
      evidenceClass: "authenticated_phone_report",
      sourceEventId: snapshot.lineage.eventId,
      sourceParentEventId: snapshot.lineage.parentEventId,
      sourceSequence: snapshot.lineage.sequence,
      semanticParentEventId:
        snapshot.lineage.parentEventId === null
          ? null
          : (this.lineage.findBySourceEventId(snapshot.lineage.parentEventId)?.eventId ?? null),
      targetPackage: snapshot.targetPackage,
      revision: snapshot.revision,
      itemCount: snapshot.items.length,
      status: "incomplete_visible_window",
    });
    this.latestSnapshot = snapshot;
    audit({
      event: "chat.updated",
      revision: snapshot.revision,
      itemCount: snapshot.items.length,
    });
    for (const waiter of this.updateWaiters) {
      if (snapshot.revision <= waiter.afterRevision) continue;
      clearTimeout(waiter.timeout);
      this.updateWaiters.delete(waiter);
      waiter.resolve(snapshot);
    }
  }

  private assertTargetPackage(targetPackage: string): void {
    const expected = this.hello?.capabilities.targetPackage;
    if (!expected || targetPackage !== expected) {
      throw new Error("Phone result did not match the configured target package");
    }
  }

  private onClose(socket: WebSocket): void {
    if (socket !== this.socket) return;
    if (this.helloTimer) clearTimeout(this.helloTimer);
    const deviceId = this.hello?.device.id;
    const targetPackage = this.hello?.capabilities.targetPackage ?? null;
    this.socket = undefined;
    this.connectedAt = undefined;
    this.latestSnapshot = undefined;
    this.expression = undefined;
    this.rejectAll(
      new RosyTalkBridgeError("PHONE_DISCONNECTED", "Phone disconnected"),
      targetPackage,
    );
    this.hello = undefined;
    this.rejectWaiters(
      new RosyTalkBridgeError("PHONE_DISCONNECTED", "Phone disconnected"),
    );
    audit(
      deviceId
        ? { event: "phone.disconnected", deviceId }
        : { event: "phone.disconnected" },
    );
  }

  private rejectAll(
    error: Error,
    targetPackage = this.hello?.capabilities.targetPackage ?? null,
  ): void {
    for (const [requestId, pending] of this.pending.entries()) {
      clearTimeout(pending.timeout);
      let rejection = error;
      if (pending.method === "chat.submit") {
        try {
          this.appendLineage({
            event: "submission.failed",
            source: "relay",
            evidenceClass: "relay_observed_outcome",
            semanticParentEventId: pending.requestLineageEventId,
            requestId,
            targetPackage,
            status: "connection_closed_indeterminate",
            code: error instanceof RosyTalkBridgeError ? error.code : "CONNECTION_CLOSED",
          }, true);
        } catch (lineageError) {
          if (lineageError instanceof Error) rejection = lineageError;
        }
      }
      if (pending.method === "room.expression") {
        try {
          this.appendLineage({
            event: "expression.failed",
            source: "relay",
            evidenceClass: "relay_observed_outcome",
            semanticParentEventId: pending.requestLineageEventId,
            requestId,
            method: "room.expression",
            status: "connection_closed_indeterminate",
            code: error instanceof RosyTalkBridgeError ? error.code : "CONNECTION_CLOSED",
          }, true);
        } catch (lineageError) {
          if (lineageError instanceof Error) rejection = lineageError;
        }
      }
      pending.reject(rejection);
    }
    this.pending.clear();
  }

  private rejectWaiters(error: Error): void {
    for (const waiter of this.updateWaiters) {
      clearTimeout(waiter.timeout);
      waiter.reject(error);
    }
    this.updateWaiters.clear();
  }
}

export type { RelayRequest };
