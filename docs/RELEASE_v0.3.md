# Aster Room / RosyTalk Bridge v0.3

## What changed

- The Android app opens as **Aster Room** with a bounded mirror of the currently visible RosyTalk conversation.
- A code-drawn Aster face supports seven explicit states: `neutral`, `thinking`, `amused`, `soft`, `fierce`, `flustered`, and `blush`.
- Expressions are never inferred from message sentiment. They change only through an explicit local selection or the authenticated `rosytalk_set_expression` MCP tool.
- Remote expression changes and RosyTalk message submission share the phone's expiring 15-minute action authorization.
- The MCP surface now contains seven tools: five chat/lineage tools plus `rosytalk_room_status` and `rosytalk_set_expression`.
- Metadata lineage records expression request/outcome ancestry without persisting the caption or conversation text.
- The Room clears mirrored text when the target package changes or Accessibility stops, identifies the captured package and time, and uses Android `FLAG_SECURE` to keep mirrored text out of ordinary screenshots and Recents thumbnails.

## Verified in this source release

- TypeScript typecheck and emitted build pass.
- Relay protocol, lineage, security, chat, and Room tests pass: **40/40**.
- The mock commissioning path exercises all seven tools, revisions `1 → 2 → 3`, an exact-bound submission, stale refusal, an explicit Room state, and the no-message-bodies/no-expression-captions lineage invariant.

## Still requires real hardware or external infrastructure

- Android `assembleDebug` and lint must run in GitHub Actions or a machine with JDK 17, Android SDK 36, and Gradle 9.3.1 available. This workspace did not have that toolchain cached.
- Accessibility capture and submit behavior must be commissioned against the actual installed RosyTalk application and selected package.
- The Secure MCP Tunnel profile, bearer header handling, and first physical conversation require the user's external account, tunnel, Windows relay, and phone.

Follow [COMMISSION_FIRST_CONVERSATION.md](COMMISSION_FIRST_CONVERSATION.md) in order. A successful mock commission is not a claim that the physical phone path has already been commissioned.
