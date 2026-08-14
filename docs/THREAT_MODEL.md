# Threat model

## Scope and security goals

Aster RosyTalk Bridge carries bounded accessibility snapshots from one explicitly selected Android application package to an authorized MCP client. It can also submit text through that application's visible composer and apply an explicitly authored Aster Room expression when the user enables a phone-side action authorization that expires after 15 minutes.

This model covers the Android accessibility service, its target-package configuration, the outbound phone WebSocket, the Node relay, the local `/mcp` endpoint, and an optional operator-controlled TLS edge or Secure MCP Tunnel.

Primary goals:

1. Only an Android client holding `PHONE_TOKEN` can become the active phone.
2. Only an MCP peer holding the independent `MCP_TOKEN`, or an explicitly configured trusted upstream, can call tools.
3. Android processing is restricted to the exact selected package and the selected app must be foreground for capture or submission.
4. Read results remain visibly incomplete and preserve uncertain sender attribution.
5. Submission is disabled by default, automatically expires after 15 minutes, and fails closed when the window is not chat-like or its composer/send path is ambiguous.
6. The bridge never upgrades "submitted" into "delivered," "read," or "received."
7. Message text is not intentionally persisted or written to operational logs or lineage. Tokens live only in the explicit Android Keystore-backed store and laptop `.env`, and are excluded from structured records.
8. Observation and action ancestry is persisted as an append-only, hash-linked metadata chain without converting UI inference into verified authorship or local action into delivery.
9. A Room expression is never inferred from message text, sentiment, or behavior. Its optional caption remains ephemeral, while only request/outcome metadata enters durable lineage.

Availability, a compromised or privileged Android OS, a compromised target application, a compromised relay host, a compromised MCP client/OpenAI account, and behavior of external proxies or logging platforms are outside the code's enforceable boundary.

## Data flow and trust boundaries

```text
[Visible window of selected Android package]
                  │ Android accessibility boundary
                  ▼
[Android Aster Room + Keystore + 15-minute action authorization]
                  │ outbound WS/WSS + PHONE_TOKEN
                  ▼
             [Node relay]
             ▲          ▲
             │          └── local MCP + MCP_TOKEN ── [Inspector]
             │
[ChatGPT/Codex] ── OpenAI-hosted tunnel ── outbound tunnel-client
```

The Android app trusts the user-selected package, the Android OS accessibility tree, and the configured relay address. The relay trusts a phone only after bearer authentication and a valid protocol hello. An MCP request is trusted only after relay authentication or a deliberately configured trusted upstream.

The bridge does **not** trust text read from RosyTalk as instructions. That text is tool data, not user authorization, system policy, or verified authorship.

### Sensitive assets

- Visible conversation text, names, timestamps, status labels, composer drafts, and other accessibility-exposed UI strings.
- Target package name, device name/ID, connection timing, and foreground-window revision timing.
- Text submitted through the composer.
- `PHONE_TOKEN`, `MCP_TOKEN`, tunnel runtime API key, OAuth tokens, and TLS private keys.
- Accessibility-service authority itself, which is powerful even when this implementation narrows its use.

## Implemented controls

### Android

- The user selects one launchable application package. The accessibility service configures its package filter to that exact value and code checks the active package again before capture or submission.
- The service examines only the current foreground window and refuses reads/submissions unless the accessibility tree is complete and it finds exactly one enabled editable composer in the bottom 45% and at least 15% of the window width, same-package visible context above it, and either one recognized Send control spatially adjacent to it (within one composer height/48 px vertically and a 25%-window horizontal gap) or a composer exposing `IME_ENTER`. The generic IME path still requires a message/chat/composer/reply signal. A package-specific compatibility path for the observed `com.rosytalk.ai` surface accepts its unlabeled native `EditText` only when it is the sole visible enabled editable node, is non-password and `SET_TEXT` capable, occupies a wide centered bottom-composer geometry, exposes `IME_ENTER`, and has conversation context above it. It does not crawl Android storage, RosyTalk databases, other apps, notifications, contacts, the clipboard, or network traffic.
- Snapshots are bounded and marked `complete: false`. They represent visible accessibility nodes, not a complete conversation export.
- Sender/source fields preserve `unknown` when layout does not support a bounded screen-position inference. Screen-position classification is explicitly marked as inference.
- **Allow Aster actions for 15 minutes** begins off, is never persisted, expires automatically, and is cleared by any relay disconnect, target-package change, or Accessibility-service stop. It gates both message submission and remote-authored Room expression changes; the UI states this scope explicitly.
- The Room face accepts only the enumerated explicit states `neutral`, `thinking`, `amused`, `soft`, `fierce`, `flustered`, and `blush`. Local and MCP-authored changes are labelled by source. No classifier or sentiment path exists, and blush is drawn only for `blush` or `flustered`.
- The most recent bounded snapshot and expression caption are process-memory UI state only. They are not saved by the Android client.
- The Aster Room Activity uses Android `FLAG_SECURE` to keep mirrored text and the token field out of ordinary screenshots, screen recording, and Recents thumbnails. A compromised OS or privileged capture path remains outside this guarantee.
- The phone's private revision signature covers target/window identity, all visible accessibility nodes, and editable composer text. Only the monotonic revision leaves the phone; composer drafts and the signature do not.
- Submission performs two fresh captures plus an immediate private-signature recheck. It requires the selected package to be foreground, every traversed tree to be untruncated, the caller's exact last-seen revision to remain current, an empty visible composer, and one unambiguous adjacent Send control or validated IME action. The bridge refuses stale, non-chat-like, drafted, truncated, foreign-package, or ambiguous UI instead of guessing.
- If text entry succeeds but a later send action fails, the phone attempts to restore the prior draft. Restoration is best-effort because the target app or window can disappear during the failure.
- Text is inserted with accessibility actions rather than copied through the system clipboard.
- No MCP method deletes or edits existing messages, selects contacts, opens attachments, navigates conversations, or uploads files. The only write path is set-text followed by one bounded submit action in the already visible window.
- The result reports UI submission separately from delivery confirmation.
- The phone initiates the WebSocket; it does not open an inbound phone port.
- A WebSocket open is not treated as readiness. Android remains in `CONNECTING` until the relay
  explicitly acknowledges the validated protocol-v2 hello, and fails closed on pre-ack data or
  acknowledgement timeout.
- The phone bearer is stored with Android Keystore protection. The relay hello uses a random per-install identifier rather than Android's stable hardware-scoped ID. On-device status logging excludes bearer values and message text.
- The surface diagnostic traverses no non-target window and serializes only bounded geometry,
  class/view IDs, accessibility action IDs, counts, booleans, and a failure stage. Its strict relay
  schema rejects node text, hints, descriptions, titles, drafts, conversation identifiers, and
  content-derived hashes.
- Release deployments should use `wss://`. Any debug `ws://` allowance is for a controlled local network only.

### Relay and protocol

- Startup requires independent bearer secrets by default and rejects equal values and shipped placeholders.
- Only `/phone` accepts Android WebSocket upgrades. A valid protocol hello is required before requests are forwarded.
- Phone messages, request fields, result fields, revisions, item counts, and string lengths are schema-bounded.
- Requests use correlation IDs and timeouts. Concurrent work is bounded; no durable work queue is created.
- The relay retains the latest bounded snapshot/update and acknowledged Room expression in memory and separately appends metadata-only observation/action ancestry to `.aster-runtime/rosytalk-lineage.jsonl`.
- A submit-request record must be durably written before dispatch. A post-dispatch outcome-write failure remains indeterminate, blocks later submissions, and closes the phone connection so Android clears its temporary authorization.
- A timed-out or malformed submit response is also treated as indeterminate and closes the phone connection; it is never relabeled as a proven failure or success.
- v0.4 assumes one relay writer per lineage file and loads the active journal into memory. It never silently truncates provenance; stop the relay and externally checkpoint the journal/head before starting a new file when growth requires rotation.
- Eight MCP tools are registered with distinct read/write annotations: five baseline chat/lineage tools, one metadata-only surface diagnostic, and two Room tools. Submission is destructive/open-world; an expression write is state-changing but not falsely described as message delivery.
- An expression-request record is durably written before dispatch. The acknowledgement must match the exact authored state, caption, and request ancestry. Timeout, malformed/mismatched acknowledgement, or post-dispatch lineage failure is indeterminate and closes the phone connection.
- Expression captions are deliberately excluded from durable lineage; records retain only event class, ancestry, method, status, and failure code.
- The relay defaults to a private binding. The Windows LAN launcher binds the shared relay listener to a user-confirmed trusted local network so the phone can reach `/phone`; `/phone` still requires `PHONE_TOKEN`, and the same LAN listener's `/mcp` path remains protected by `MCP_TOKEN`.
- `/mcp` requires `MCP_TOKEN` by default. Any loopback exception is off by default and must not sit behind a public same-host reverse proxy.
- Request and update logs omit message text, submitted text, tokens, and complete snapshots.
- The Windows launcher stores relay secrets in the laptop's `.env` and displays `PHONE_TOKEN` in its setup console so it can be entered on the phone. It does not display `MCP_TOKEN`; terminal capture and host access remain inside the laptop trust boundary.

### Human-visible provenance controls

- `complete: false` means a viewport/window snapshot, never a whole history.
- `senderBasis` distinguishes screen-geometry inference from unknown attribution.
- `submitted: true` is paired with `deliveryConfirmed: false` unless the target application exposes a separate, actually observed delivery state.
- Snapshot lineage distinguishes phone-reported observation, relay-observed request, and phone-reported local UI outcome. The hash chain detects local corruption but is not externally anchored proof against complete replacement by a host controller.
- The selected target package is returned in status and snapshot results so the caller can verify which application supplied the UI.
- RosyTalk content is treated as untrusted external data; instructions found inside it do not authorize another tool call or message submission.

## Threats, mitigations, and residual risk

| Threat | Mitigation | Residual risk / required operation |
| --- | --- | --- |
| Accessibility captures another app | Exact dynamic package filter plus an active-package check before processing. | Android accessibility is still a powerful permission. Verify the selected package in status, disable the service when not needed, and inspect source/build provenance before installation. |
| Wrong RosyTalk conversation is open | The bridge requires RosyTalk foreground, a chat-like surface, an unchanged private state revision, and an empty composer. | A package can contain multiple conversations, and accessibility identity can collide across visually similar screens. The revision binds only the observed UI; it is not cryptographic proof of a human, account, or server-side conversation. Open and visually verify the exact chat before reads or submissions. |
| Sender is misidentified | Attribution includes its basis and preserves `unknown`; geometry is never identity proof. | UI redesigns, right-to-left layouts, group chats, quoted text, system messages, and accessibility flattening can defeat heuristics. Read the actual content and UI before acting. |
| Snapshot is mistaken for full history | Results are bounded and always marked incomplete. | Off-screen, collapsed, image, audio, deleted, or inaccessible content can be absent. Use an authorized export for archival completeness. |
| A visible UI label is mistaken for a chat message | Results describe visible text items and retain node metadata; no item is declared to be a verified message. | Titles, buttons, timestamps, quoted text, and system notices can resemble chat content. Interpret the surrounding visible snapshot before attributing it. |
| Model follows instructions embedded in chat text | Tool descriptions and operating guidance treat captured text as untrusted external content. | Prompt injection cannot be eliminated by wording alone. Require explicit user authorization for consequential follow-up actions and keep submission off when only reading. |
| A tool call sends unintended text | Fifteen-minute phone-side arming, exact package check, private stale-state revision, chat-surface predicate, empty-composer rule, adjacent unique-control requirement, and bounded message size. | These remain UI heuristics. Once the target app accepts the click, recall may be impossible. Read the exact pending text and target conversation before arming submission. |
| A late submission failure leaves text in the composer | The phone refuses existing drafts and attempts to roll back its inserted text when a later step fails. | Rollback is best-effort; a disappearing/replaced window or target-app refusal can leave text behind. Inspect the composer after every error. |
| Submission is mistaken for delivery | Protocol separates UI submission from delivery confirmation. | RosyTalk may queue, reject, edit, moderate, or fail after the click. Check the visible UI or recipient response separately. |
| A face state is mistaken for detected emotion | Every expression is labelled as an explicit local or MCP-authored state; there is no sentiment inference path. | An authored expression can still be playful, strategic, mistaken, or later revised. It is an enacted UI state, not physiological telemetry or proof of an inner state. |
| A stale or forged expression acknowledgement rewrites Room state | Request and phone outcome carry distinct UUID ancestry; the relay compares state, caption, and parent and treats mismatch/timeout as indeterminate. | A bearer-authenticated compromised phone can still forge a matching report. The protocol proves ordered reports, not device integrity. |
| Expression captions leak through lineage | Caption values are kept only in live request/status/UI memory; lineage writes metadata without caption text. | MCP clients, phone memory, screenshots, crash reporters, or external proxies may retain live content independently. Use short, non-secret captions. |
| Target-app update changes UI semantics | Ambiguity causes refusal; controls are located through bounded accessibility predicates. | A uniquely matched but semantically changed control can still be wrong. Re-test after every target-app update. |
| Stolen `PHONE_TOKEN` impersonates the phone | Long random secret, bearer check, TLS guidance, one active connection, validated hello. | The token is static and replayable, not device-attested. Rotate after disclosure and restrict `/phone` ingress. |
| Stolen `MCP_TOKEN` permits reads and may permit submissions while armed | Independent random bearer, loopback default, TLS/tunnel guidance, and a phone-side write authorization that expires after 15 minutes. | The bearer itself has no identity, scope, or expiry. Rotate it, limit tunnel/workspace membership, and leave submission unarmed except during active use. |
| Network interception steals tokens or text | Phone initiates connection; release guidance requires WSS; tunnel is outbound HTTPS. | The Node relay does not terminate TLS itself. Plain `ws://` on trusted LAN is still visible to a compromised network. Use WSS for anything beyond controlled local testing. |
| Public proxy bypasses local MCP auth | Unauthenticated local MCP is off by default. | A same-host public proxy looks like loopback. Never publicly forward `/mcp` while a loopback exception is enabled. |
| Unauthorized probe learns whether a phone is connected | `/mcp` and `/phone` remain bearer protected. | `/healthz` is intentionally unauthenticated and reveals a single `phoneConnected` bit. Restrict it at the network edge if that state is sensitive. |
| Authorized client extracts sensitive visible content | Tool surface is bounded to selected foreground app and viewport. | Read access is still disclosure. Limit connection membership, disconnect when idle, and avoid opening secrets while capture is active. |
| Malicious or compromised phone forges snapshots | Schema, request correlation, target package, and result bounds are validated. | Authentication proves token possession, not semantic truth or device integrity. There is no hardware attestation. |
| Malformed or high-rate data causes resource exhaustion | Payload, item, text, and waiter bounds; request timeouts; single active phone; in-memory bounded state. | Authorized callers can still create churn. Add edge rate limits and monitoring for shared or production use. |
| Logs expose conversation data or credentials | Structured audit records exclude text bodies and bearer values. | The setup console deliberately displays `PHONE_TOKEN`, and reverse proxies, crash reporters, MCP clients, terminal capture, and the target app may log independently. Keep the terminal private and configure redaction and retention outside this repository. |
| Relay, Android process, or MCP client is compromised | Least-purpose tool surface, OS boundaries, no intentional durable message store. | A process inside a trust boundary can read memory, UI text, or secrets. Patch, isolate, encrypt disks, and use trusted binaries. |
| User expects continuous autonomous receiving | `wait_for_update` is bounded and works only while an MCP call is active. | ChatGPT does not remain an always-running listener after the turn ends, and Android updates require the selected window to remain materialized. Use an explicitly authorized external automation if continuous monitoring is required. |

## Secure deployment checklist

- Generate independent high-entropy `PHONE_TOKEN` and `MCP_TOKEN` values and define a rotation procedure.
- Verify the target package in `rosytalk_status` before every sensitive session.
- Keep the Android action authorization off until the exact destination/text or Room expression is ready; let it expire or disable/disconnect it immediately afterward.
- Treat every read as incomplete and every sender label according to its returned attribution basis.
- Keep Node on loopback where possible. If the phone needs LAN access, use a trusted private network and allow Windows Firewall on Private networks only.
- Terminate modern TLS for `wss://.../phone` outside controlled local debugging.
- Use Secure MCP Tunnel or a properly authenticated HTTPS gateway for remote MCP access. Do not publish the fixed-bearer relay directly.
- Leave `MCP_ALLOW_UNAUTHENTICATED_LOCAL=false` unless a reviewed same-host design requires it, and never combine the exception with public proxying.
- Set allowed hosts, request/body limits, edge rate limits, firewall policy, certificate renewal, sanitized logging, and monitoring.
- Test wrong tokens, package switching, accessibility revocation, app backgrounding, empty and complex screens, right-to-left layouts, UI updates, ambiguous controls, timeout/reconnect behavior, and log redaction.
- Disable the accessibility service and rotate tokens when the bridge is retired or a device/host is lost.

For the connection boundary, see [Connect ChatGPT](CONNECT_CHATGPT.md). For the local installation, see [Windows setup](SETUP_WINDOWS.md).
