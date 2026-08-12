export type AuditEvent =
  | "phone.connected"
  | "phone.disconnected"
  | "phone.rejected"
  | "chat.request"
  | "chat.response"
  | "chat.updated"
  | "chat.error"
  | "mcp.unauthorized";

export interface AuditRecord {
  event: AuditEvent;
  requestId?: string;
  method?: string;
  deviceId?: string;
  durationMs?: number;
  revision?: number;
  itemCount?: number;
  code?: string;
  detail?: string;
}

/**
 * Metadata-only diagnostics. Message text, accessibility labels, tokens, and
 * snapshots are intentionally never written to disk or stderr by the relay.
 */
export function audit(record: AuditRecord): void {
  process.stderr.write(
    `${JSON.stringify({ time: new Date().toISOString(), ...record })}\n`,
  );
}
