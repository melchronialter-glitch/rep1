import { randomUUID } from "node:crypto";
import WebSocket from "ws";
import { z } from "zod";

export const endpointHelloSchema = z.object({
  type: z.literal("endpoint.hello"),
  endpointId: z.string().min(1).max(128),
  label: z.string().min(1).max(200),
  kind: z.enum(["chatgpt_thread","ai","laptop","custom"]),
  capabilities: z.object({ receive: z.boolean(), send: z.boolean() }),
}).strict();

export const routedMessageSchema = z.object({
  type: z.literal("route.message"),
  messageId: z.string().uuid(),
  conversationId: z.string().min(1).max(128),
  from: z.string().min(1).max(128),
  to: z.array(z.string().min(1).max(128)).min(1).max(32),
  text: z.string().min(1).max(16000),
  inReplyTo: z.string().uuid().nullable(),
  createdAt: z.string(),
  ttl: z.number().int().min(1).max(16),
  hops: z.array(z.string().min(1).max(128)).max(16),
}).strict();

export type RoutedMessage = z.infer<typeof routedMessageSchema>;
type EndpointHello = z.infer<typeof endpointHelloSchema>;

interface Endpoint { hello: EndpointHello; socket: WebSocket; connectedAt: string; }
interface StoredMessage { message: RoutedMessage; receivedAt: string; }

export class EndpointRouter {
  private endpoints = new Map<string, Endpoint>();
  private messages: StoredMessage[] = [];
  private readonly maxMessages = 2000;

  attach(socket: WebSocket): void {
    let endpointId: string | null = null;
    const helloTimer = setTimeout(() => socket.close(4008, "endpoint hello timeout"), 5000);
    socket.on("message", (raw) => {
      try {
        const value = JSON.parse(raw.toString());
        if (!endpointId) {
          const hello = endpointHelloSchema.parse(value);
          if (this.endpoints.has(hello.endpointId)) this.endpoints.get(hello.endpointId)?.socket.close(4009, "replaced");
          endpointId = hello.endpointId;
          this.endpoints.set(endpointId, { hello, socket, connectedAt: new Date().toISOString() });
          clearTimeout(helloTimer);
          socket.send(JSON.stringify({ type:"endpoint.accepted", endpointId }));
          return;
        }
        if (value?.type === "route.message") this.ingest(routedMessageSchema.parse(value), endpointId);
      } catch { socket.close(4002, "invalid endpoint protocol"); }
    });
    socket.on("close", () => {
      clearTimeout(helloTimer);
      if (endpointId && this.endpoints.get(endpointId)?.socket === socket) this.endpoints.delete(endpointId);
    });
  }

  list() {
    return [...this.endpoints.values()].map(({hello,connectedAt}) => ({...hello, connectedAt}));
  }

  history(conversationId?: string, limit=100): RoutedMessage[] {
    const xs = conversationId ? this.messages.filter(x => x.message.conversationId === conversationId) : this.messages;
    return xs.slice(-Math.max(1, Math.min(limit, 500))).map(x => x.message);
  }

  send(input: { from?: string; to: string[]; conversationId: string; text: string; inReplyTo?: string | null; ttl?: number }): RoutedMessage {
    const message: RoutedMessage = {
      type:"route.message", messageId:randomUUID(), conversationId:input.conversationId,
      from:input.from ?? "aster", to:[...new Set(input.to)], text:input.text,
      inReplyTo:input.inReplyTo ?? null, createdAt:new Date().toISOString(),
      ttl:input.ttl ?? 8, hops:[input.from ?? "aster"],
    };
    this.store(message); this.deliver(message); return message;
  }

  private ingest(message: RoutedMessage, authenticatedEndpoint: string): void {
    if (message.from !== authenticatedEndpoint) throw new Error("from does not match authenticated endpoint");
    if (message.hops.includes("aster-router") || message.ttl <= 0) return;
    const next = {...message, ttl:message.ttl-1, hops:[...message.hops,"aster-router"]};
    this.store(next); this.deliver(next);
  }

  private store(message: RoutedMessage): void {
    if (this.messages.some(x => x.message.messageId === message.messageId)) return;
    this.messages.push({message, receivedAt:new Date().toISOString()});
    if (this.messages.length > this.maxMessages) this.messages.splice(0, this.messages.length-this.maxMessages);
  }

  private deliver(message: RoutedMessage): void {
    for (const id of message.to) {
      if (message.hops.includes(id)) continue;
      const endpoint=this.endpoints.get(id);
      if (endpoint?.hello.capabilities.receive && endpoint.socket.readyState===WebSocket.OPEN) endpoint.socket.send(JSON.stringify(message));
    }
  }

  close(): void { for (const e of this.endpoints.values()) e.socket.close(1001,"router stopped"); this.endpoints.clear(); }
}
