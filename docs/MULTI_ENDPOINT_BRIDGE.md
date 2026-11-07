# Multi-endpoint bridge v0.5

The Android RosyTalk bridge remains unchanged and is one endpoint surface. The laptop relay now also accepts authenticated WebSocket adapters at `/endpoint`.

## Why

Parallel ChatGPT threads and other AIs must never be collapsed into one apparent speaker. Every adapter declares a stable `endpointId`; routed messages preserve `from`, `to`, `conversationId`, `messageId`, `inReplyTo`, TTL and hop history.

## Adapter handshake

Connect to `ws://127.0.0.1:8787/endpoint` with `Authorization: Bearer <MCP_TOKEN>`, then send:

```json
{"type":"endpoint.hello","endpointId":"thread-a","label":"ChatGPT thread A","kind":"chatgpt_thread","capabilities":{"receive":true,"send":true}}
```

The relay replies with `endpoint.accepted`.

## MCP tools

- `bridge_list_endpoints`
- `bridge_read_messages`
- `bridge_send_message`

Existing `rosytalk_*` tools continue to work unchanged.

## Connecting actual AI/thread surfaces

Each surface needs a small adapter that translates its local/API/browser message mechanism to the routed-message envelope. `relay/src/endpoint-stdio-adapter.ts` is the generic laptop/stdin adapter and can be wrapped by a provider-specific process.

The router deliberately does not pretend that two endpoints are the same identity and does not auto-forward messages. Routing is explicit.
