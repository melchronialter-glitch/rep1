# Aster Room / RosyTalk Bridge v0.4.2

## Why this patch exists

Physical-phone commissioning exposed a lineage gap after a correctly refused stale submission.
The Android stale check captured a changed window and advanced its private observation revision,
then returned `STALE_SNAPSHOT` without publishing that observation. A later public snapshot could
therefore name the hidden observation as its parent, which the relay correctly rejected as an
invalid phone response.

## What changed

- A submission validation capture that discovers a newer revision is published before the stale
  error is returned.
- Publication occurs before the error response and before any composer mutation or send action.
- Both the initial stale check and the immediate pre-mutation revalidation use the same guard.
- Same-revision/different-observation-ID results remain rejected and are not published, because
  that shape cannot safely extend the relay's current lineage.
- Relay integration coverage exercises revision 1 read, revision 2 publication, stale refusal,
  and a valid revision 3 descendant.
- Android unit coverage checks update-before-refusal ordering, both validation stages, identity
  mismatches, and fresh-snapshot no-ops.

## Compatibility and installation

- The relay protocol remains version 2; existing v0.4 and v0.4.1 relay/tunnel setups remain
  compatible.
- Android `versionCode` is 6 and `versionName` is `0.4.2`.
- An already desynchronized v0.4.1 session can recover without reinstalling: toggle the temporary
  Aster action authorization off and on to force a fresh authenticated phone connection, then
  take a new snapshot before submitting.
- A debug APK built with a different debug signing key cannot update an existing debug install.
  Preserve the current working installation when the reconnect recovery is sufficient.

## Verification

- TypeScript check/build and all 46 relay tests pass locally.
- Android unit tests and `assembleDebug` pass in
  [GitHub Actions run 31823289760](https://github.com/melchronialter-glitch/rep1/actions/runs/31823289760)
  for commit `3614e8cdb1d5c71a3047182f2b2887a57fed1f91`.
- The verified debug APK SHA-256 is
  `b714cc228fcac920ea5378c8ea25cb2eeaf8660f404b2f3fa06f6a43f9576c94`.
- Physical-phone acceptance still requires a fresh visible read, a revision-bound `ime_enter`
  action, and a newer visible response. A successful local UI action is not proof of delivery.
