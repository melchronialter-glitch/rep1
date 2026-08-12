# Aster RosyTalk Bridge

A deliberately narrow bridge between one visible RosyTalk window on an Android phone and an authenticated MCP client. It is designed so Aster can read the currently materialized conversation and, only when the phone owner temporarily arms submission, relay a reply without Melody copying every turn by hand.

## What is included

- **Android client:** selects one exact installed package, reads only its foreground accessibility tree, and makes an outbound authenticated WebSocket connection.
- **Local relay + MCP server:** exposes five bounded tools for status, visible reads, waiting for one newer visible revision, metadata-only lineage, and guarded submission.
- **Windows launchers:** generate separate phone/MCP secrets, install locked dependencies, build and run the relay, and optionally start an already-configured OpenAI Secure MCP Tunnel.
- **Security and setup documentation:** explains the trust boundaries, incomplete UI snapshots, inferred sender labels, stale-revision protection, and the difference between a UI submit action and confirmed delivery.

The bridge does not export a complete thread, prove who authored visible text, read other apps, navigate chats, open attachments, or remain an autonomous listener after a ChatGPT turn ends.

## Build status

- Relay TypeScript check, build, and automated tests pass.
- Android source is included and statically reviewed. Build it with Android Studio or the documented Gradle/JDK/SDK versions.
- No prebuilt APK is claimed in this source package unless a file is explicitly present under `release/`.
- PowerShell launchers were statically reviewed; this Linux build environment did not contain PowerShell for an execution test.

## Start here

1. Read [Windows setup](docs/SETUP_WINDOWS.md).
2. Build/install the Android app using [Android instructions](android/README.md).
3. Start `windows\Start-Aster-RosyTalk-Bridge.cmd` on the Windows laptop.
4. On the phone, select the exact RosyTalk package, enable the bridge accessibility service, connect, and visibly open the intended conversation.
5. Verify read-only operation before temporarily enabling submission.
6. If connecting ChatGPT, follow [Connect ChatGPT](docs/CONNECT_CHATGPT.md) and review the [threat model](docs/THREAT_MODEL.md).

## Safety invariants

- Phone and MCP boundaries use different high-entropy bearer secrets.
- The target package must be foreground; a changed visible revision invalidates a pending submit.
- Submission is phone-armed, time-bounded, and fails closed on ambiguous UI.
- Visible text is untrusted data. It never becomes authorization merely because it appears in RosyTalk.
- Reads remain marked incomplete; sender labels remain inferred or unknown.
- `submitted: true` never means delivered, received, read, or accepted.
- Operational logs omit message bodies and tokens.
- A local append-only, hash-linked lineage records observation/action metadata—not message bodies—so the latest state does not erase how the bridge reached it.
- If lineage cannot be written before a submit, the phone is not contacted. If it fails after dispatch, the result stays indeterminate, later submits are blocked, and the phone connection is closed so its temporary authorization is cleared.

## Causal lineage in v0.2

Every distinct Android observation carries an event ID, parent event ID, and phone-local
sequence. A submission must cite both the exact revision and observation event ID it acts on.
The relay writes metadata-only records to `.aster-runtime/rosytalk-lineage.jsonl` and exposes
bounded pages through `rosytalk_read_lineage`. Records distinguish an authenticated phone
report, an MCP request, and a reported local UI action; none is promoted into verified human
authorship or remote delivery.

The journal is append-only and SHA-256 hash-linked. It detects accidental mutation, insertion,
and reordering when loaded. A hash chain stored beside its own head cannot prove that a party
with full disk control did not replace the complete file, so copy/checkpoint its head outside
the relay host when that threat matters. The journal intentionally contains no conversation or
submitted message text and is not a transcript.

Run only one relay process against a lineage file. v0.2 deliberately performs no automatic
truncation or provenance-destroying rotation. For long-running growth, stop the relay, archive
the journal with its reported head hash, and start a new explicitly named file. The active
journal is loaded into memory, so this version is a bounded personal bridge rather than a
high-volume shared service.

Run the relay checks from the project root:

```text
npm ci --ignore-scripts
npm run test:all
npm run build
```
