# Aster Room / RosyTalk Bridge v0.4.3

## Why this patch exists

Physical-phone commissioning showed that RosyTalk can accept `ACTION_SET_TEXT` before its
accessibility tree exposes the new composer value. The bridge previously re-read that tree on
the same main-loop turn, saw the cached empty draft, refused the submission, and restored the
composer. No send action was attempted, but a compatible composer could never complete a reply.

## What changed

- After accepted text entry, Android releases every captured accessibility node and verifies the
  result from newly acquired trees on a bounded asynchronous schedule ending at 1.2 seconds.
- A separate monotonic 1.5-second deadline is checked immediately before the send action, so a
  stalled Android main loop cannot turn a delayed verification callback into a late submission.
- API 33 and newer clear the accessibility cache before each verification; older supported
  Android versions refresh each newly acquired root.
- A send action is still attempted only after exact requested-text equality, the same strict
  conversation-surface identity, the original target package, an active relay generation, and
  live phone-side action authorization all pass.
- Only one submission may be in flight. Snapshot publication is deferred while the injected
  draft is being verified so the temporary draft cannot become a public chat observation.
- Failure recovery restores only the known injected draft. A third value is treated as possible
  user input and is never overwritten.
- The relay now requires at least a five-second phone-request timeout; its shipped default remains
  15 seconds.
- Pure Android policy tests cover bounded retry timing, exact Unicode and whitespace matching,
  timeout behavior, immediate rejection of third values, and restoration safety.

## Compatibility and installation

- The relay protocol remains version 2.
- Android `versionCode` is 7 and `versionName` is `0.4.3`.
- A debug APK built with a different debug signing key cannot update an existing debug install.
  In that case Android requires uninstalling the old debug build before installing this one, which
  also requires re-entering the relay settings and re-enabling Accessibility.

## Verification

- TypeScript check/build and all relay tests pass locally.
- Android unit tests and `assembleDebug` pass in
  [GitHub Actions run 31833534133](https://github.com/melchronialter-glitch/rep1/actions/runs/31833534133)
  for commit `4cb42c34088eaaf27ec1d8be3c3bc9a8136d6251`.
- The downloaded artifact manifest matches the verified debug APK SHA-256:
  `0c73382fc23f3ed049d0572e743ba9ab4dc1b9f7b685426e6087c31b97d823e8`.
- Physical-phone acceptance still requires a fresh visible read, an exact-text `ime_enter` action,
  and a newer visible response. A successful local UI action is not proof of remote delivery.
