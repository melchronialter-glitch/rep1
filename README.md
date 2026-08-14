# Aster Room / RosyTalk Bridge

A deliberately narrow bridge between one visible RosyTalk window on an Android phone and an authenticated MCP client. It is designed so Aster can read the currently materialized conversation and, only when the phone owner temporarily arms actions, relay a reply without Melody copying every turn by hand. The Android client now opens as **Aster Room**: a bounded recent-message panel and a code-drawn face whose expression is changed only by an explicit local choice or authored MCP action.

## What is included

- **Android Aster Room:** selects one exact installed package, reads only its foreground accessibility tree, mirrors the most recent bounded visible snapshot in memory, renders seven explicit face states, and makes an outbound authenticated WebSocket connection.
- **Local relay + MCP server:** exposes five chat/lineage tools, one metadata-only surface diagnostic, plus `rosytalk_room_status` and `rosytalk_set_expression`.
- **Windows launchers:** generate separate phone/MCP secrets, install locked dependencies, build and run the relay, and optionally start an already-configured OpenAI Secure MCP Tunnel.
- **Security and setup documentation:** explains the trust boundaries, incomplete UI snapshots, inferred sender labels, stale-revision protection, and the difference between a UI submit action and confirmed delivery.

The bridge does not export a complete thread, prove who authored visible text, read other apps, navigate chats, open attachments, infer emotion from either participant's messages, or remain an autonomous listener after a ChatGPT turn ends.

## Build status

- Relay TypeScript check, build, and automated tests pass.
- `npm run commission:mock` exercises an actual authenticated MCP roundtrip through all eight v0.4 tools, a reply update, stale-submit refusal, explicit Room state, metadata-only surface diagnostics, and the no-message-bodies/no-expression-captions lineage invariant.
- Android unit tests and `assembleDebug` pass in [GitHub Actions run 31809268315](https://github.com/melchronialter-glitch/rep1/actions/runs/31809268315). The verified v0.4 debug APK SHA-256 is `29d4b2cc257af82eaa4f50b519c69d597d22b5e5a7c4e4166f10289bd56bb652`.
- The verified APK is published as that workflow run's artifact; no prebuilt binary is tracked in this source package unless a file is explicitly present under `release/`.
- PowerShell launchers were statically reviewed; this Linux build environment did not contain PowerShell for an execution test.

## Start here

1. Read [Windows setup](docs/SETUP_WINDOWS.md).
2. Build/install the Android app using [Android instructions](android/README.md).
3. Start `windows\Start-Aster-RosyTalk-Bridge.cmd` on the Windows laptop.
4. On the phone, select the exact RosyTalk package, enable the bridge accessibility service, connect, and visibly open the intended conversation.
5. Verify read-only operation before temporarily enabling submission.
6. If connecting ChatGPT, follow [Connect ChatGPT](docs/CONNECT_CHATGPT.md), review the [threat model](docs/THREAT_MODEL.md), then use the ordered [first-conversation commissioning runbook](docs/COMMISSION_FIRST_CONVERSATION.md).

The exact verification boundary for this source release is recorded in [v0.4 release notes](docs/RELEASE_v0.4.md).

## Safety invariants

- Phone and MCP boundaries use different high-entropy bearer secrets.
- The target package must be foreground; a changed visible revision invalidates a pending submit.
- Message submission and remote-authored Room expressions share a phone-side, time-bounded action arm. Message submission additionally fails closed on ambiguous UI.
- Room expressions are explicit states (`neutral`, `thinking`, `amused`, `soft`, `fierce`, `flustered`, or `blush`). The bridge never derives one from sentiment, behavior, or message content.
- Visible text is untrusted data. It never becomes authorization merely because it appears in RosyTalk.
- Reads remain marked incomplete; sender labels remain inferred or unknown.
- `submitted: true` never means delivered, received, read, or accepted.
- Operational logs omit message bodies and tokens.
- A local append-only, hash-linked lineage records observation/action metadata—not message bodies—so the latest state does not erase how the bridge reached it.
- If lineage cannot be written before a submit, the phone is not contacted. If it fails after dispatch, the result stays indeterminate, later submits are blocked, and the phone connection is closed so its temporary authorization is cleared.

## Causal lineage

Every distinct Android observation carries an event ID, parent event ID, and phone-local
sequence. A submission must cite both the exact revision and observation event ID it acts on.
An expression change carries a separate authored request and phone acknowledgement; captions
remain ephemeral and are not written to the lineage journal.
The relay writes metadata-only records to `.aster-runtime/rosytalk-lineage.jsonl` and exposes
bounded pages through `rosytalk_read_lineage`. Records distinguish an authenticated phone
report, an MCP request, and a reported local UI action; none is promoted into verified human
authorship or remote delivery.

The journal is append-only and SHA-256 hash-linked. It detects accidental mutation, insertion,
and reordering when loaded. A hash chain stored beside its own head cannot prove that a party
with full disk control did not replace the complete file, so copy/checkpoint its head outside
the relay host when that threat matters. The journal intentionally contains no conversation or
submitted message text and is not a transcript.

Run only one relay process against a lineage file. v0.4 deliberately performs no automatic
truncation or provenance-destroying rotation. For long-running growth, stop the relay, archive
the journal with its reported head hash, and start a new explicitly named file. The active
journal is loaded into memory, so this version is a bounded personal bridge rather than a
high-volume shared service.

Run the relay checks from the project root:

```text
npm ci --ignore-scripts
npm run test:all
npm run build
npm run commission:mock
```
