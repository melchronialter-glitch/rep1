# Aster Room / RosyTalk Bridge v0.4.1

## Why this patch exists

Physical-phone commissioning reached the real `com.rosytalk.ai` conversation surface. The v0.4
diagnostic found one native `android.widget.EditText`, an exposed `IME_ENTER` action, and visible
conversation context above it, but RosyTalk supplied no message-like hint, content description, or
view ID. The generic v0.4 recognizer therefore refused the valid surface at
`message_composer_signal_missing`.

## What changed

- The unlabeled-IME exception is restricted to the exact observed `com.rosytalk.ai` package.
- It requires a sole visible enabled editable node, native `EditText`, non-password state,
  `SET_TEXT`, `IME_ENTER`, wide centered bottom geometry, and same-package conversation context.
- Generic selected applications retain the v0.4 lexical message/chat/composer/reply requirement.
- Reads and every submission traversal now refuse truncated accessibility trees instead of trying
  to establish control uniqueness from an incomplete tree.
- Exported visible text, composer candidates, Send candidates, and context evidence are restricted
  to nodes belonging to the foreground target package.
- A pure host-testable policy covers the observed live geometry and the acceptance/refusal matrix.

## Compatibility and installation

- The relay protocol remains version 2 and the existing v0.4 relay/tunnel is compatible.
- Android `versionCode` is 5 and `versionName` is `0.4.1`.
- A debug APK built with a different debug signing key cannot update an existing debug install.
  In that case, uninstall v0.4 before installing v0.4.1, then restore the relay URL/token, selected
  RosyTalk package, Accessibility permission, and the temporary action switch as needed.

## Verified in this patch

- TypeScript check/build and all 45 relay tests pass.
- The Android policy tests and `assembleDebug` pass in
  [GitHub Actions run 31819719889](https://github.com/melchronialter-glitch/rep1/actions/runs/31819719889)
  for commit `d4268e96788f76402cd6c2c470b7139be009ad00`.
- The verified debug APK SHA-256 is
  `b61bb9d618036b5edfa35c47f97d9bd8c834ab9e0ae88a1f13a666bd0bb60807`.

Physical-phone acceptance still requires a successful `rosytalk_read_visible`, a revision-bound
`ime_enter` submission, and a newer visible response read through the bridge. A local UI action is
not represented as remote delivery.
