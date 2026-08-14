# Aster Room / RosyTalk Bridge v0.4

## What changed

- Fresh physical-phone debug installs no longer receive the emulator-only `10.0.2.2` relay
  address. They start blank and point to the exact private-LAN URL printed by the Windows launcher;
  emulator installs retain the `10.0.2.2` convenience default.
- A token-free, redirect-free, 4 KiB-bounded **Test relay reachability** action verifies
  `/healthz` and separates DNS, routing, TCP, firewall, timeout, TLS, wrong-port, and HTTP failures
  from later bearer authentication.
- Android remains in `CONNECTING` until the relay explicitly returns `hello.accepted` for protocol
  v2. A socket open by itself is no longer represented as protocol readiness.
- The Android activity log now has a bounded, process-local, defensively redacted replay ring, so
  connection outcomes survive the setup screen leaving the foreground without persisting content.
- The MCP surface contains eight tools. New `rosytalk_diagnose_surface` reports strictly bounded
  target-window geometry, control class/view IDs, accessibility action IDs, counts, recognition
  booleans, and the exact failure stage. Its strict schema cannot carry node text, hints, content
  descriptions, window titles, composer drafts, conversation identifiers, or content-derived
  hashes.
- MCP request cleanup is registered before handling and runs exactly once across response
  `finish`, `close`, or an exception.
- The Windows relay launcher probes both loopback and its selected LAN address, prints an explicit
  physical-phone browser check, and runs a fresh locked `npm ci` on every start.
- The Secure MCP Tunnel helper now documents and checks its supported ephemeral environment flow,
  including separate discovery/call bearer headers, while leaving named profiles optional.

## Compatibility

- The wire protocol remains version 2. The acknowledgement is a backward-compatible relay event:
  a v0.3 phone ignores it and can still use a v0.4 relay.
- A v0.4 phone intentionally requires the acknowledgement, so pair it with the v0.4 relay. When
  connected to an older relay it times out with an explicit update/restart message instead of
  claiming readiness.

## Verified in this source release

- TypeScript typecheck and emitted build pass.
- Relay protocol, security, cleanup, chat, Room, diagnostic, and lineage tests pass: **45/45**.
- The mock commissioning path exercises all eight tools, revisions `1 → 2 → 3`, an exact-bound
  submission, stale refusal, an explicit Room state, the metadata-only diagnostic boundary, and
  the no-message-bodies/no-expression-captions lineage invariant.
- Diff whitespace validation passes.

## Requires CI, real hardware, or external infrastructure

- This environment cannot download the uncached Gradle 9.3.1 distribution. GitHub Actions is
  configured to run the new Android unit tests before `assembleDebug`; the v0.4 APK must not be
  claimed until that workflow passes and publishes its SHA-256 artifact.
- The PowerShell launchers were reviewed statically because PowerShell is unavailable here.
- Accessibility recognition and submit behavior still require commissioning against the exact
  installed RosyTalk version and selected package.
- Secure MCP Tunnel readiness and the first physical conversation require the user's external
  account, tunnel, Windows relay, phone, and current official `tunnel-client` binary.

Follow [COMMISSION_FIRST_CONVERSATION.md](COMMISSION_FIRST_CONVERSATION.md) in order. A successful
mock commission is not a claim that the physical phone path has already been commissioned.
