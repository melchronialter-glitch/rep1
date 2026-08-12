# Aster RosyTalk Bridge for Android

This is the phone client for the RosyTalk relay in the parent project. It reads only the
currently materialized accessibility tree of one explicitly selected Android package and can
submit text only while that package is the foreground window.

It does not read notifications, the clipboard, files, photos, or any other app window. It opens
no inbound phone port: the app makes an authenticated outbound WebSocket connection to
`/phone`.

## Build

- Android Gradle Plugin 9.1.1 with built-in Kotlin support
- Gradle 9.3.1
- JDK 17
- Android SDK 36
- `compileSdk` / `targetSdk` 36; `minSdk` 29

```bash
./gradlew :app:assembleDebug
```

The installable APK is written to `app/build/outputs/apk/debug/app-debug.apk`.

## Setup

1. Start the relay with its `PHONE_TOKEN` configured.
2. Open the Android app and choose RosyTalk from the installed launchable-app list. The package
   name shown beside the app label is the actual boundary Android enforces.
3. Enter the relay WebSocket URL and matching phone token.
4. Tap **Open Accessibility settings** and enable **RosyTalk conversation bridge**.
5. Return to the bridge and tap **Connect**.
6. Open the intended RosyTalk conversation. Enable **Allow message submission for 15 minutes**
   only when you want the bridge to submit replies.

The emulator debug default is `ws://10.0.2.2:8787/phone`. Debug builds accept `ws://` for local
development. Release builds require `wss://` in both code and Android network policy.

The phone token field is masked. Its saved value is AES/GCM ciphertext, while the non-exportable
AES key is held by Android Keystore. Android backups are disabled.

## Enforced scope

The service applies two independent checks:

- `AccessibilityServiceInfo.packageNames` is set to exactly the selected target package, so
  Android filters delivered events.
- Every event and every active root is checked against that exact package before the tree is
  traversed.

Before a target is selected, the service filters itself rather than accepting events from all
packages. Changing the selected target immediately refreshes the Android-level filter and the
relay capability hello.

Snapshots are accepted only when the target window exposes one unambiguous bottom composer plus
either a spatially adjacent Send control or an explicit message-composer IME send action, with
visible conversation context above it. They are explicitly marked `complete: false`:
accessibility exposes only the visible, materialized window, not a complete transcript. `sender`
is `remote`, `self`, or `unknown`, and `senderBasis` is `screen_geometry` or `unknown`; left/right
geometry is never represented as verified authorship.

## Submission safeguard

**Allow message submission for 15 minutes** is off at Activity launch, automatically expires,
is disabled on target change, Accessibility shutdown, or any relay disconnect, and is never persisted. Even while armed, submission
is rejected unless the selected target is the foreground chat surface described above. Ambiguity
is an error; the bridge does not guess and never uses the clipboard. A non-empty local composer
is also an error, so a user's existing draft is never intentionally overwritten.

A successful local action returns `submitted: true` and `deliveryConfirmed: false`. It does not
claim that RosyTalk or the remote participant delivered or received the text.

## Phone protocol

After the authenticated protocol-v2 hello, the phone handles exactly:

- `chat.snapshot` with optional `maxItems` from 1 to 200
- `chat.submit` with nonblank `text` up to 16,000 characters plus the `expectedRevision` and
  `expectedSnapshotId` returned by the exact visible snapshot Aster acted on

When visible target content changes, the phone pushes a `chat.updated` event carrying the same
incomplete snapshot shape. The relay may use those revisions to implement waiting for a reply.
Submission performs a fresh full snapshot before touching the input field and returns
`STALE_SNAPSHOT` if the visible revision differs from `expectedRevision`. The private revision
signature includes root/window identity and editable composer text, but the draft itself is not
transmitted. The window is revalidated immediately before mutation. After text entry, the client
re-resolves and matches the same window, composer, and send-control identity and verifies the
visible header/conversation-context signature, then verifies the exact requested text before
clicking or invoking IME. If a later action fails, draft restoration
is attempted only when that exact same surface and composer still match; it will not clear an
unrelated field after navigation.
Each distinct visible state also receives a UUID lineage event, a parent event pointer, and a
phone-local sequence. The relay persists only the lineage metadata; message bodies remain
ephemeral. A submit result echoes the exact snapshot event and revision it acted on, while still
reporting `deliveryConfirmed: false`.
The bounded on-screen activity log records only connection/method outcomes and is not persisted;
it never includes credentials or conversation text.
