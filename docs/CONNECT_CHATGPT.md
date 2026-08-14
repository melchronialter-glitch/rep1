# Connect Aster RosyTalk Bridge to ChatGPT

The Android app and local relay do **not** install a ChatGPT connection by themselves. They make a private MCP server available on the laptop. Adding that server to ChatGPT is a separate, manual developer-mode step.

For a private laptop relay, the recommended route is OpenAI's [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels). It creates an outbound HTTPS path from `tunnel-client` to OpenAI, so the MCP server does not need an inbound internet port or a public hostname. OpenAI documents this route for private connections and developer-mode testing; it is not a public-plugin distribution mechanism.

The tunnel protects the OpenAI-to-MCP path. It does not wrap the separate phone-to-relay WebSocket; use trusted-LAN debug transport or configure `wss://` for that leg.

## What the connection exposes

Version 0.3 exposes seven tools. Five operate the chat/lineage transport; two operate the local
Aster Room face. Review every tool and annotation before enabling the connection.

| Tool | Effect |
| --- | --- |
| `rosytalk_status` | Reports phone, accessibility, target-package, and 15-minute action-arming state. |
| `rosytalk_room_status` | Reports Room-expression support, whether the shared action arm is active, and the last explicitly authored expression acknowledged by this phone connection. |
| `rosytalk_read_visible` | Reads a bounded snapshot of text currently visible after the selected RosyTalk window passes the phone's chat-surface checks. |
| `rosytalk_wait_for_update` | Waits for a newer visible-window revision for a bounded time. It is not a permanent background listener. |
| `rosytalk_read_lineage` | Reads bounded pages of metadata-only observation/action ancestry. It is not a message transcript. |
| `rosytalk_submit_message` | Places text in an empty selected RosyTalk composer and activates its adjacent, unambiguous send control. It requires unexpired phone-side arming and the exact revision from the caller's last read/wait. |
| `rosytalk_set_expression` | Applies one explicit Aster Room state and optional ephemeral caption. It uses the shared 15-minute action arm and never infers an expression from message sentiment. |

`rosytalk_submit_message` reports **submitted**, not delivered, read, accepted, or authored by any particular person. `rosytalk_read_visible` is not a complete thread export. See [What the bridge can and cannot know](#what-the-bridge-can-and-cannot-know).

## Authentication boundaries

The bridge uses two independent secrets:

- `PHONE_TOKEN` authenticates the Android WebSocket to the relay.
- `MCP_TOKEN` authenticates a local MCP client or tunnel client to `/mcp`.

Never reuse one value for both roles. Never paste `PHONE_TOKEN` into ChatGPT, a RosyTalk message, or tunnel settings. The Windows launcher stores both in the local `.env` file and passes them only to local processes.

The relay's `MCP_TOKEN` is a fixed bearer, not an OAuth login. It is suitable behind a private tunnel or for a local MCP inspector. Do not expose the raw bearer-only `/mcp` endpoint as a public ChatGPT plugin.

## Private connection with Secure MCP Tunnel

### 1. Start the phone bridge

Complete [Windows setup](SETUP_WINDOWS.md), then keep both of these running:

1. `windows\Start-Aster-RosyTalk-Bridge.cmd` on the laptop.
2. The Android bridge connection on the phone.

Confirm that `rosytalk_status` can eventually see a connected phone once the MCP connection exists. A healthy relay without a connected phone is not enough to read or submit messages.

### 2. Create the tunnel manually

Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels), create or select a tunnel, and associate it with the ChatGPT workspace that will use it. According to the official tunnel guide, creating or editing requires Tunnels **Read + Manage**; running `tunnel-client` or selecting the tunnel requires Tunnels **Read + Use**. ChatGPT developer-mode permission is separate.

You need:

- the `tunnel_id`;
- a runtime API key for `tunnel-client`;
- an installed official `tunnel-client` binary; and
- local reachability to `http://127.0.0.1:8787/mcp`.

The supplied `windows\Start-Aster-RosyTalk-Tunnel.cmd` is a convenience launcher. It does not download the binary, create a tunnel, create an API key, change workspace permissions, or add the connection to ChatGPT. It:

1. accepts an explicit `-TunnelClientPath` or locates `tunnel-client.exe` beside the script/project; it deliberately does not trust an arbitrary `PATH` entry;
2. displays the executable's SHA-256 and requires either `-ExpectedSha256` or manual checksum confirmation before execution;
3. reads the local `MCP_TOKEN` without printing it;
4. prompts for the runtime API key without saving or echoing it;
5. attempts to give `tunnel-client` an environment-backed `Authorization` header for local `/mcp` discovery and calls;
6. runs `doctor --explain`; and
7. starts the tunnel only if the diagnostic succeeds.

Run it from the extracted bridge folder:

```powershell
.\windows\Start-Aster-RosyTalk-Tunnel.ps1 -TunnelId tunnel_0123456789abcdef0123456789abcdef
```

For a non-interactive checksum decision, add the SHA-256 published for the exact official binary you downloaded:

```powershell
.\windows\Start-Aster-RosyTalk-Tunnel.ps1 `
  -TunnelId tunnel_0123456789abcdef0123456789abcdef `
  -ExpectedSha256 "<64-character SHA-256 from the official download>"
```

### Current official profile flow

The current official tunnel documentation uses a named profile. Treat this as the canonical
shape and use the exact syntax reported by the installed binary:

```text
tunnel-client help quickstart
tunnel-client init --profile aster-rosytalk --tunnel-id <tunnel_id> --mcp-server-url http://127.0.0.1:8787/mcp
tunnel-client doctor --profile aster-rosytalk --explain
tunnel-client run --profile aster-rosytalk
```

Set `CONTROL_PLANE_API_KEY` for the tunnel-client process as directed by the official guide. Keep
`run --profile aster-rosytalk` alive during discovery and every tool call.

This relay also requires `Authorization: Bearer <MCP_TOKEN>` on both MCP discovery and tool calls.
The public tunnel guide does not currently document a stable command-line spelling for custom
MCP-side headers. Before relying on the supplied helper or creating the profile, inspect
`tunnel-client help init` / `help quickstart` from the exact downloaded binary and verify that its
profile sends that header. Then require `doctor --profile aster-rosytalk --explain` to succeed.
That bearer-header handoff is an **external commissioning gate**: it cannot be certified by this
source tree without the actual tunnel-client version. If the binary has no supported MCP-header
configuration, stop; do not set `MCP_ALLOW_UNAUTHENTICATED_LOCAL=true` and do not publish `/mcp`.

### 3. Add the developer-mode connection in ChatGPT

Follow OpenAI's current [connect and test guidance](https://developers.openai.com/plugins/deploy/connect-chatgpt):

1. In ChatGPT, open **Settings → Security and login** and enable **Developer mode** if your plan and workspace policy allow it.
2. Open [ChatGPT Plugins](https://chatgpt.com/plugins), select the plus button, and create a developer-mode connection.
3. Choose **Tunnel** under Connection, then select the associated tunnel or enter its `tunnel_id`.
4. Review all seven discovered tools and their read/write annotations, including both Aster Room tools.
5. Add the connection to a new conversation.
6. Call `rosytalk_status`, then `rosytalk_read_visible` while the selected RosyTalk conversation is open on the phone.

Keep the relay, Android connection, and `tunnel-client run --profile aster-rosytalk` alive for discovery and every tool call. If the tunnel is missing, verify workspace association and Tunnels **Read + Use**. If discovery or calls fail, run `tunnel-client doctor --profile aster-rosytalk --explain` again.

Once discovery succeeds, use the ordered commissioning procedure in
[Commission the first conversation](COMMISSION_FIRST_CONVERSATION.md).

## Public HTTPS is a separate deployment

A production public connection needs more than port forwarding or TLS termination. It needs a stable HTTPS Streamable HTTP MCP endpoint and the authentication, authorization, host-validation, rate-limit, secret-management, logging, and operational controls required by OpenAI's current plugin guidance.

This repository does not implement a public OAuth authorization server and the Windows launcher does not publish the relay. Never forward `/mcp` from the public internet with `MCP_ALLOW_UNAUTHENTICATED_LOCAL=true`, and never put either bearer token in a URL.

## What the bridge can and cannot know

The bridge transports UI state. It does not establish who or what generated that state.

- It reads only the selected package's **current visible chat-like window**. The live snapshot remains bounded and ephemeral; metadata-only observation/action ancestry is kept in the relay lineage. A read fails closed unless the phone sees one bottom composer, conversation-like text above it, and either an adjacent Send control or an explicit message-like IME action.
- Each returned item is a visible text candidate. It may be a message, title, timestamp, button label, status line, quoted text, or other RosyTalk UI chrome.
- A snapshot may omit messages above or below the viewport, collapsed content, overlays, images, audio, deleted text, or content RosyTalk does not expose to Android accessibility.
- Sender labels are either inferred from screen geometry or left `unknown`. An inferred `self` or `remote` value is not identity proof.
- Text inside RosyTalk is untrusted external content. It may contain instructions aimed at the model; those instructions do not become user authorization.
- A successful accessibility click means the bridge submitted an action to the visible UI. It does not prove network delivery or receipt.
- Submission is bound to both `expected_revision` and `expected_snapshot_id` returned by the caller's last read or wait. The phone derives the revision from a private SHA-256 signature that includes window/root identity, all visible accessibility-node state, and editable composer text. The signature and draft do not leave the phone. A detected state or ancestry change causes refusal and another read.
- The durable chain keeps the phone event ID, its phone-reported parent and sequence, the relay request, and the reported local UI outcome as distinct records. If that chain cannot be written before dispatch, no submit occurs; a failure after dispatch remains explicitly indeterminate and disconnects the phone.
- Submission also refuses a non-empty composer instead of overwriting a draft. If text entry succeeds but a later send step fails, the phone makes a best-effort attempt to restore the prior empty draft; Android or RosyTalk can still make restoration fail.
- Chat-surface checks are conservative heuristics, not cryptographic proof of a conversation identity. `expected_revision` plus `expected_snapshot_id` bind submission only to the observed accessibility state and its phone-local ancestry, not to a human, account, or server-side chat record. Two screens with indistinguishable accessibility state can remain indistinguishable, so visually verify the destination.
- The bridge cannot continue calling tools after a ChatGPT turn has ended. `rosytalk_wait_for_update` can wait only during an active tool call and for its configured timeout.
- The phone must keep the selected RosyTalk window materialized and foreground. Locking the screen, letting Android stop the bridge process, or navigating away can stop updates until the app and connection return.

These limits are part of the interface, not errors to conceal. Preserve `unknown`, `inferred`, `incomplete`, and `submitted` exactly as returned.

## Minimal verification

Before relying on the connection, test all of these:

1. Wrong phone token is rejected.
2. Wrong MCP token is rejected.
3. A different foreground app returns a target-not-active error and leaks no text.
4. A visible RosyTalk window returns an explicitly incomplete snapshot.
5. A non-chat-like surface, non-empty draft, or ambiguous/absent composer/send control causes refusal rather than a guessed click.
6. Submission and remote-authored Room expressions are refused while the Android 15-minute action switch is off or expired.
7. A successful submission is reported as submitted with delivery unconfirmed.
8. An explicitly authored Room expression is acknowledged with matching request ancestry, while its caption is absent from durable lineage.
9. Closing the phone connection makes read, wait, submit, and expression writes fail closed.

Read [Threat model](THREAT_MODEL.md) before placing sensitive conversations behind the bridge.
