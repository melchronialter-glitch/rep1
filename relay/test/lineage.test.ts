import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, test, type TestContext } from "node:test";
import { LineageStore } from "../src/lineage.js";

function temporaryPath(t: TestContext): string {
  const directory = mkdtempSync(join(tmpdir(), "aster-rosytalk-lineage-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return join(directory, "lineage.jsonl");
}

describe("RosyTalk metadata lineage", () => {
  test("persists an ordered hash chain and resumes it after restart", (t) => {
    const path = temporaryPath(t);
    const store = new LineageStore(path);
    const observed = store.append({
      event: "snapshot.observed",
      source: "android_bridge",
      evidenceClass: "authenticated_phone_report",
      sourceEventId: "11111111-1111-4111-8111-111111111111",
      targetPackage: "com.example.rosytalk",
      revision: 1,
      itemCount: 2,
      status: "incomplete_visible_window",
    });
    const requested = store.append({
      event: "submission.requested",
      source: "mcp_client",
      evidenceClass: "relay_observed_request",
      semanticParentEventId: observed.eventId,
      requestId: "22222222-2222-4222-8222-222222222222",
      revision: 1,
      status: "requested",
    });

    assert.equal(requested.sequence, 2);
    assert.equal(requested.previousHash, observed.recordHash);

    const reopened = new LineageStore(path);
    assert.deepEqual(reopened.summary(), {
      entries: 2,
      headSequence: 2,
      headHash: requested.recordHash,
    });
    const final = reopened.append({
      event: "submission.enacted",
      source: "android_bridge",
      evidenceClass: "authenticated_phone_report",
      semanticParentEventId: requested.eventId,
      status: "local_ui_action_only",
    });
    assert.equal(final.sequence, 3);
    assert.equal(final.previousHash, requested.recordHash);
  });

  test("deduplicates a repeated authenticated phone source event", (t) => {
    const store = new LineageStore(temporaryPath(t));
    const sourceEventId = "33333333-3333-4333-8333-333333333333";
    const first = store.append({
      event: "snapshot.observed",
      source: "android_bridge",
      evidenceClass: "authenticated_phone_report",
      sourceEventId,
      revision: 1,
    });
    const second = store.append({
      event: "snapshot.observed",
      source: "android_bridge",
      evidenceClass: "authenticated_phone_report",
      sourceEventId,
      revision: 1,
    });
    assert.equal(second.eventId, first.eventId);
    assert.equal(store.summary().entries, 1);
  });

  test("rejects source-event collisions and missing semantic parents", (t) => {
    const store = new LineageStore(temporaryPath(t));
    const sourceEventId = "77777777-7777-4777-8777-777777777777";
    store.append({
      event: "snapshot.observed",
      source: "android_bridge",
      evidenceClass: "authenticated_phone_report",
      sourceEventId,
      revision: 1,
      itemCount: 1,
    });

    assert.throws(
      () =>
        store.append({
          event: "snapshot.observed",
          source: "android_bridge",
          evidenceClass: "authenticated_phone_report",
          sourceEventId,
          revision: 2,
          itemCount: 2,
        }),
      /reused with different lineage metadata/,
    );
    assert.throws(
      () =>
        store.append({
          event: "submission.requested",
          source: "mcp_client",
          evidenceClass: "relay_observed_request",
          semanticParentEventId: "88888888-8888-4888-8888-888888888888",
        }),
      /semantic parent is missing/,
    );
  });

  test("rejects mutation and partial tail instead of silently repairing", (t) => {
    const path = temporaryPath(t);
    const store = new LineageStore(path);
    store.append({
      event: "snapshot.observed",
      source: "android_bridge",
      evidenceClass: "authenticated_phone_report",
      sourceEventId: "44444444-4444-4444-8444-444444444444",
      targetPackage: "com.example.rosytalk",
      revision: 1,
    });

    const original = readFileSync(path, "utf8");
    writeFileSync(path, original.replace("com.example.rosytalk", "com.example.changed"));
    assert.throws(() => new LineageStore(path), /Broken lineage hash/);

    writeFileSync(path, original.trimEnd());
    assert.throws(() => new LineageStore(path), /partial record/);
  });

  test("rejects injected unknown fields instead of hashing a sanitized record", (t) => {
    const path = temporaryPath(t);
    const store = new LineageStore(path);
    store.append({
      event: "snapshot.observed",
      source: "android_bridge",
      evidenceClass: "authenticated_phone_report",
      sourceEventId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      revision: 1,
    });
    const record = JSON.parse(readFileSync(path, "utf8").trim()) as Record<string, unknown>;
    record.messageBody = "INJECTED CONTENT MUST INVALIDATE THE RECORD";
    writeFileSync(path, `${JSON.stringify(record)}\n`);
    assert.throws(() => new LineageStore(path), /unrecognized|messageBody/i);
  });

  test("preserves an unresolved phone parent and its phone-local order", (t) => {
    const store = new LineageStore(temporaryPath(t));
    const sourceParentEventId = "99999999-9999-4999-8999-999999999999";
    const observed = store.append({
      event: "snapshot.observed",
      source: "android_bridge",
      evidenceClass: "authenticated_phone_report",
      sourceEventId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      sourceParentEventId,
      sourceSequence: 42,
      semanticParentEventId: null,
      revision: 7,
    });
    assert.equal(observed.sourceParentEventId, sourceParentEventId);
    assert.equal(observed.sourceSequence, 42);
    assert.equal(observed.semanticParentEventId, null);
  });

  test("never persists message bodies supplied outside metadata fields", (t) => {
    const path = temporaryPath(t);
    const store = new LineageStore(path);
    store.append({
      event: "submission.requested",
      source: "mcp_client",
      evidenceClass: "relay_observed_request",
      requestId: "55555555-5555-4555-8555-555555555555",
      targetPackage: "com.example.rosytalk",
      status: "requested",
    });
    const bytes = readFileSync(path, "utf8");
    assert.doesNotMatch(bytes, /SECRET MESSAGE BODY/);
    assert.doesNotMatch(bytes, /deviceId/);
    assert.match(bytes, /submission\.requested/);
  });

  test("paginates metadata without promoting it into a transcript", (t) => {
    const store = new LineageStore(temporaryPath(t));
    for (let revision = 1; revision <= 3; revision += 1) {
      store.append({
        event: "snapshot.observed",
        source: "android_bridge",
        evidenceClass: "authenticated_phone_report",
        sourceEventId: `66666666-6666-4666-8666-66666666666${revision}`,
        revision,
      });
    }
    const page = store.page(0, 2);
    assert.equal(page.scope, "metadata_only");
    assert.equal(page.records.length, 2);
    assert.equal(page.hasMore, true);
    assert.equal(page.nextAfterSequence, 2);
  });
});
