import { randomUUID } from "node:crypto";
import WebSocket from "ws";

const relay = process.env.ASTER_RELAY_WS ?? "ws://127.0.0.1:8787/endpoint";
const token = process.env.MCP_TOKEN;
const endpointId = process.env.ASTER_ENDPOINT_ID ?? "laptop-1";
if (!token) throw new Error("MCP_TOKEN is required");

const ws = new WebSocket(relay, { headers:{ Authorization:`Bearer ${token}` } });
ws.on("open", () => ws.send(JSON.stringify({
  type:"endpoint.hello", endpointId,
  label:process.env.ASTER_ENDPOINT_LABEL ?? endpointId,
  kind:(process.env.ASTER_ENDPOINT_KIND ?? "laptop"),
  capabilities:{receive:true,send:true},
})));
ws.on("message", raw => {
  const msg=JSON.parse(raw.toString());
  process.stdout.write(JSON.stringify(msg)+"\n");
});
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => {
  for (const line of chunk.split(/\r?\n/).filter(Boolean)) {
    const input=JSON.parse(line);
    ws.send(JSON.stringify({
      type:"route.message",
      messageId:input.messageId ?? randomUUID(),
      conversationId:input.conversationId ?? "default",
      from:endpointId,
      to:input.to,
      text:input.text,
      inReplyTo:input.inReplyTo ?? null,
      createdAt:new Date().toISOString(),
      ttl:input.ttl ?? 8,
      hops:[endpointId],
    }));
  }
});
