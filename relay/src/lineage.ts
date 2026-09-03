import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  fstatSync,
  statSync,
  writeSync,
} from "node:fs";
import { dirname, resolve } from "node:path";
import { z } from "zod";

const lineageEventSchema = z.enum([
  "snapshot.observed",
  "submission.requested",
  "submission.enacted",
  "submission.failed",
  "expression.requested",
  "expression.enacted",
  "expression.failed",
]);

const lineageSourceSchema = z.enum(["android_bridge", "mcp_client", "relay"]);
const evidenceClassSchema = z.enum([
  "authenticated_phone_report",
  "relay_observed_request",
  "relay_observed_outcome",
]);

const nullableId = z.string().uuid().nullable();
const nullableText = z.string().max(500).nullable();

export const storedLineageRecordSchema = z.object({
  schemaVersion: z.literal(1),
  sequence: z.number().int().positive().max(Number.MAX_SAFE_INTEGER),
  eventId: z.string().uuid(),
  recordedAt: z.string().refine((value) => !Number.isNaN(Date.parse(value))),
  event: lineageEventSchema,
  source: lineageSourceSchema,
  evidenceClass: evidenceClassSchema,
  sourceEventId: nullableId,
  sourceParentEventId: nullableId,
  sourceSequence: z.number().int().positive().max(Number.MAX_SAFE_INTEGER).nullable(),
  semanticParentEventId: nullableId,
  requestId: nullableId,
  targetPackage: nullableText,
  revision: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER).nullable(),
  itemCount: z.number().int().nonnegative().max(200).nullable(),
  method: nullableText,
  status: nullableText,
  code: nullableText,
  previousHash: z.string().regex(/^[a-f0-9]{64}$/).nullable(),
  recordHash: z.string().regex(/^[a-f0-9]{64}$/),
}).strict();

export type StoredLineageRecord = z.infer<typeof storedLineageRecordSchema>;

export interface LineageAppend {
  event: z.infer<typeof lineageEventSchema>;
  source: z.infer<typeof lineageSourceSchema>;
  evidenceClass: z.infer<typeof evidenceClassSchema>;
  sourceEventId?: string | null;
  sourceParentEventId?: string | null;
  sourceSequence?: number | null;
  semanticParentEventId?: string | null;
  requestId?: string | null;
  targetPackage?: string | null;
  revision?: number | null;
  itemCount?: number | null;
  method?: string | null;
  status?: string | null;
  code?: string | null;
}

export interface LineagePage {
  scope: "metadata_only";
  records: StoredLineageRecord[];
  headSequence: number;
  headHash: string | null;
  hasMore: boolean;
  nextAfterSequence: number;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, stableValue(item)]),
    );
  }
  return value;
}

function hashPayload(value: object): string {
  return createHash("sha256").update(JSON.stringify(stableValue(value))).digest("hex");
}

function withoutRecordHash(record: StoredLineageRecord): Omit<StoredLineageRecord, "recordHash"> {
  const { recordHash: _recordHash, ...payload } = record;
  return payload;
}

interface BackingFileIdentity {
  dev: bigint;
  ino: bigint;
  size: bigint;
  mtimeNs: bigint;
  ctimeNs: bigint;
}

function identityFromStats(
  stats: ReturnType<typeof statSync> & {
    dev: bigint;
    ino: bigint;
    size: bigint;
    mtimeNs: bigint;
    ctimeNs: bigint;
  },
): BackingFileIdentity {
  return {
    dev: stats.dev,
    ino: stats.ino,
    size: stats.size,
    mtimeNs: stats.mtimeNs,
    ctimeNs: stats.ctimeNs,
  };
}

function sameBackingFile(left: BackingFileIdentity, right: BackingFileIdentity): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.size === right.size &&
    left.mtimeNs === right.mtimeNs &&
    left.ctimeNs === right.ctimeNs
  );
}

/**
 * Append-only, metadata-only bridge history. It preserves causal order and
 * action ancestry without persisting conversation or submitted message text.
 */
export class LineageStore {
  private readonly path: string;
  private readonly entries: StoredLineageRecord[] = [];
  private readonly eventIndex = new Map<string, StoredLineageRecord>();
  private readonly sourceEventIndex = new Map<string, StoredLineageRecord>();
  private backingFile: BackingFileIdentity;

  constructor(path: string) {
    this.path = resolve(path);
    mkdirSync(dirname(this.path), { recursive: true, mode: 0o700 });
    if (!existsSync(this.path)) {
      const descriptor = openSync(this.path, "a", 0o600);
      closeSync(descriptor);
    }
    this.load();
    this.backingFile = this.readBackingIdentity();
  }

  summary(): { entries: number; headSequence: number; headHash: string | null } {
    const head = this.entries.at(-1);
    return {
      entries: this.entries.length,
      headSequence: head?.sequence ?? 0,
      headHash: head?.recordHash ?? null,
    };
  }

  findBySourceEventId(sourceEventId: string): StoredLineageRecord | null {
    return this.sourceEventIndex.get(sourceEventId) ?? null;
  }

  append(input: LineageAppend): StoredLineageRecord {
    if (input.sourceEventId) {
      const existing = this.sourceEventIndex.get(input.sourceEventId);
      if (existing) {
        const sameEvent =
          existing.event === input.event &&
          existing.source === input.source &&
          existing.evidenceClass === input.evidenceClass &&
          existing.sourceParentEventId === (input.sourceParentEventId ?? null) &&
          existing.sourceSequence === (input.sourceSequence ?? null) &&
          existing.semanticParentEventId === (input.semanticParentEventId ?? null) &&
          existing.requestId === (input.requestId ?? null) &&
          existing.targetPackage === (input.targetPackage ?? null) &&
          existing.revision === (input.revision ?? null) &&
          existing.method === (input.method ?? null) &&
          existing.status === (input.status ?? null) &&
          existing.code === (input.code ?? null);
        if (!sameEvent) {
          throw new Error("Source event ID was reused with different lineage metadata");
        }
        return existing;
      }
    }
    if (
      input.semanticParentEventId &&
      !this.eventIndex.has(input.semanticParentEventId)
    ) {
      throw new Error("Lineage semantic parent is missing or not earlier");
    }

    const head = this.entries.at(-1);
    const payload = {
      schemaVersion: 1 as const,
      sequence: (head?.sequence ?? 0) + 1,
      eventId: randomUUID(),
      recordedAt: new Date().toISOString(),
      event: input.event,
      source: input.source,
      evidenceClass: input.evidenceClass,
      sourceEventId: input.sourceEventId ?? null,
      sourceParentEventId: input.sourceParentEventId ?? null,
      sourceSequence: input.sourceSequence ?? null,
      semanticParentEventId: input.semanticParentEventId ?? null,
      requestId: input.requestId ?? null,
      targetPackage: input.targetPackage ?? null,
      revision: input.revision ?? null,
      itemCount: input.itemCount ?? null,
      method: input.method ?? null,
      status: input.status ?? null,
      code: input.code ?? null,
      previousHash: head?.recordHash ?? null,
    };
    const record = storedLineageRecordSchema.parse({
      ...payload,
      recordHash: hashPayload(payload),
    });

    this.assertBackingFileUnchanged();
    const encoded = Buffer.from(`${JSON.stringify(record)}\n`, "utf8");
    const descriptor = openSync(this.path, "a", 0o600);
    try {
      const opened = identityFromStats(fstatSync(descriptor, { bigint: true }));
      if (!sameBackingFile(opened, this.backingFile)) {
        throw new Error("Lineage backing file changed before append");
      }
      let offset = 0;
      while (offset < encoded.length) {
        const written = writeSync(descriptor, encoded, offset, encoded.length - offset);
        if (written <= 0) throw new Error("Lineage append made no forward progress");
        offset += written;
      }
      fsyncSync(descriptor);
      const afterWrite = identityFromStats(fstatSync(descriptor, { bigint: true }));
      if (afterWrite.size !== this.backingFile.size + BigInt(encoded.length)) {
        throw new Error("Lineage append length was not durable as expected");
      }
      const pathAfterWrite = this.readBackingIdentity();
      if (
        pathAfterWrite.dev !== afterWrite.dev ||
        pathAfterWrite.ino !== afterWrite.ino ||
        pathAfterWrite.size !== afterWrite.size
      ) {
        throw new Error("Lineage backing path changed during append");
      }
      this.backingFile = pathAfterWrite;
    } finally {
      closeSync(descriptor);
    }

    this.entries.push(record);
    this.eventIndex.set(record.eventId, record);
    if (record.sourceEventId) this.sourceEventIndex.set(record.sourceEventId, record);
    return record;
  }

  page(afterSequence: number, limit: number): LineagePage {
    const boundedLimit = Math.max(1, Math.min(200, Math.trunc(limit)));
    const startIndex = Math.max(0, Math.trunc(afterSequence));
    const records = this.entries.slice(startIndex, startIndex + boundedLimit);
    const head = this.entries.at(-1);
    return {
      scope: "metadata_only",
      records,
      headSequence: head?.sequence ?? 0,
      headHash: head?.recordHash ?? null,
      hasMore: startIndex + records.length < this.entries.length,
      nextAfterSequence: records.at(-1)?.sequence ?? afterSequence,
    };
  }

  private load(): void {
    const raw = readFileSync(this.path, "utf8");
    if (raw.length === 0) return;
    const lines = raw.split("\n");
    if (lines.at(-1) !== "") {
      throw new Error("Lineage file ends with a partial record");
    }
    lines.pop();

    let previousHash: string | null = null;
    let expectedSequence = 1;
    for (const [index, line] of lines.entries()) {
      if (!line || line.length > 32_768) {
        throw new Error(`Invalid lineage record at line ${index + 1}`);
      }
      let parsedJson: unknown;
      try {
        parsedJson = JSON.parse(line);
      } catch {
        throw new Error(`Invalid lineage JSON at line ${index + 1}`);
      }
      const record = storedLineageRecordSchema.parse(parsedJson);
      if (record.sequence !== expectedSequence || record.previousHash !== previousHash) {
        throw new Error(`Broken lineage order at line ${index + 1}`);
      }
      if (hashPayload(withoutRecordHash(record)) !== record.recordHash) {
        throw new Error(`Broken lineage hash at line ${index + 1}`);
      }
      if (this.eventIndex.has(record.eventId)) {
        throw new Error(`Duplicate lineage event ID at line ${index + 1}`);
      }
      if (
        record.semanticParentEventId &&
        !this.eventIndex.has(record.semanticParentEventId)
      ) {
        throw new Error(`Unknown or future semantic parent at line ${index + 1}`);
      }
      if (record.sourceEventId && this.sourceEventIndex.has(record.sourceEventId)) {
        throw new Error(`Duplicate source event in lineage at line ${index + 1}`);
      }
      this.entries.push(record);
      this.eventIndex.set(record.eventId, record);
      if (record.sourceEventId) this.sourceEventIndex.set(record.sourceEventId, record);
      previousHash = record.recordHash;
      expectedSequence += 1;
    }
  }

  private readBackingIdentity(): BackingFileIdentity {
    return identityFromStats(statSync(this.path, { bigint: true }));
  }

  private assertBackingFileUnchanged(): void {
    let current: BackingFileIdentity;
    try {
      current = this.readBackingIdentity();
    } catch {
      throw new Error("Lineage backing file is missing or inaccessible");
    }
    if (!sameBackingFile(current, this.backingFile)) {
      throw new Error("Lineage backing file changed outside the relay");
    }
  }
}
