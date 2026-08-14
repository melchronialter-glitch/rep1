# Windows one-click setup

This setup connects one Android phone to a relay on a Windows laptop. It does not install a ChatGPT connection; that optional step is documented separately in [Connect ChatGPT](CONNECT_CHATGPT.md).

## Requirements

- Windows 10 or 11.
- Node.js 20 or newer, including `npm`.
- Internet access on the laptop when `npm ci` cannot satisfy the locked relay dependencies from
  the local npm cache.
- The Aster RosyTalk Bridge debug APK for trusted-LAN `ws://` testing, or a release APK plus a configured `wss://` endpoint.
- An Android phone and laptop on the same trusted private Wi-Fi for local `ws://` testing, or an Android emulator using `ws://10.0.2.2:8787/phone`.
- The RosyTalk application already installed on the phone.

Do not use the plain local-WebSocket path on cafe, hotel, guest, workplace, or other untrusted networks. Use a `wss://` endpoint for remote or production deployment.

## 1. Start the laptop relay

Extract the complete project folder, then double-click:

```text
windows\Start-Aster-RosyTalk-Bridge.cmd
```

The launcher:

1. checks Node.js and npm;
2. chooses a private laptop IPv4 address visible to the phone;
3. asks for explicit confirmation if Windows does not report the network as Private;
4. generates separate 256-bit `PHONE_TOKEN` and `MCP_TOKEN` values on first run;
5. stores them in the local `.env` file;
6. runs a fresh locked `npm ci --ignore-scripts` and compiles the relay, preventing an older
   `node_modules` tree from surviving a source update; and
7. starts the relay after probing `/healthz` through both loopback and the selected LAN address on
   the laptop.

Those laptop-side probes verify the listener and selected address, not the physical phone's route.
Open the printed LAN `/healthz` URL in the phone browser before configuring Aster Room; that
separate check can reveal Wi-Fi client isolation or Windows Firewall blocking.

`.env` is a local plaintext secret file. Keep the Windows account and project folder private, never include `.env` in an archive, and do not send it for troubleshooting. The supplied bundle builder excludes it.

If Windows Firewall asks, allow Node.js on **Private networks only**. Keep the relay window open.

Use `-RotateTokens` from PowerShell to replace both local secrets:

```powershell
.\windows\Start-Aster-RosyTalk-Bridge.ps1 -RotateTokens
```

Rotating invalidates the phone's saved token and any local/tunnel MCP bearer configuration. Re-enter the new phone token and restart the tunnel client.

## 2. Configure the Android bridge

Install the APK, then open **Aster Room**.

On Android 13 and newer, a manually installed APK may be prevented from enabling an
Accessibility service until the phone owner explicitly allows its restricted settings. If
Android shows that block, first verify that you installed the intended APK, then open
**Settings → Apps → Aster Room → ⋮ → Allow restricted settings** and authenticate.
Return to Accessibility settings afterward. Menu names and placement vary by manufacturer; do
not disable broader device protections merely to make this bridge start.

1. Select the exact RosyTalk app from the launchable-app list. Verify its package name in the bridge UI.
2. Enter the relay URL printed by the Windows launcher, for example `ws://192.168.1.25:8787/phone`.
3. Enter the printed `PHONE_TOKEN`. Do not enter `MCP_TOKEN` on the phone.
4. Tap **Open Accessibility settings**. Leaving the setup Activity saves the URL, selected package, and Keystore-encrypted phone token.
5. Enable **RosyTalk conversation bridge** under **Aster Room**.
6. Return to the bridge and tap **Connect**.
7. Leave **Allow Aster actions for 15 minutes** off while testing read-only access.

The phone makes the outbound WebSocket connection. No inbound phone port is opened.

## 3. Open the exact conversation

Open RosyTalk and visually select the conversation you intend to bridge. Keep the phone unlocked and that RosyTalk window foreground while reading, waiting, or submitting.

The package restriction selects the app, not a particular chat inside the app. You must verify the conversation onscreen. Switching to another app causes capture and submission to fail closed; switching to another RosyTalk chat changes which visible conversation the bridge sees. A RosyTalk window must also pass the phone's conservative chat-surface checks before it can be read.

## 4. Verify locally before enabling submission

After adding the MCP connection, run these checks in order:

1. `rosytalk_status` shows the expected device, exact target package, accessibility enabled, and submission disabled.
2. `rosytalk_read_visible` returns only text from the foreground RosyTalk window and reports `complete: false`.
3. Switch to another app and confirm `rosytalk_read_visible` fails without returning that app's text.
4. Return to RosyTalk and call `rosytalk_wait_for_update` while a new visible message arrives.
5. Make sure the composer is empty. Only then enable **Allow Aster actions for 15 minutes** and submit a harmless test message using the exact revision returned by the last read/wait.

Read the result literally: `submitted: true` with `deliveryConfirmed: false` means an accessibility action was accepted by the visible UI. It is not proof of network delivery.

## Stopping and revoking

- Press Ctrl+C or type `STOP` in the relay window, depending on the launcher prompt.
- Tap **Disconnect** in the Android app.
- Turn the Aster-actions switch off; it also expires automatically after 15 minutes and is cleared on disconnect, target change, or Accessibility-service stop.
- Disable the Android accessibility service when the bridge is not needed.
- Delete `.env` only if you intend to discard both secrets; otherwise use `-RotateTokens` for controlled replacement.

## Troubleshooting

### Phone cannot connect

- Confirm the phone and laptop share the same trusted Wi-Fi.
- Open the printed `/healthz` URL in the phone browser.
- Confirm Windows Firewall allowed Node.js on Private networks.
- Confirm the phone URL ends with `/phone` and uses the laptop IPv4, not `localhost`.
- Re-enter `PHONE_TOKEN` carefully. It is different from `MCP_TOKEN`.
- For the standard Android emulator, use `10.0.2.2` as the host address.

### Connected, but reads fail

- Enable the accessibility service.
- Verify the selected package in `rosytalk_status`.
- Put RosyTalk and the exact conversation in the foreground.
- Check whether RosyTalk exposes that content to accessibility. Images, canvas-rendered text, audio, and off-screen content may be unavailable.

### Sender labels look wrong

Sender role may be inferred from layout. Group chats, quoted messages, right-to-left layouts, centered system notices, and RosyTalk UI changes can make inference wrong. Use the returned basis and keep uncertain attribution as `unknown`.

### Submission is refused

- Enable the phone-side 15-minute Aster-actions switch and confirm it has not expired.
- Keep RosyTalk foreground.
- Make sure the composer is empty and the screen exposes conversation text plus one visible bottom composer and one adjacent Send control (or an explicit message IME action).
- If RosyTalk changed its UI, do not force a guessed click; update and re-test the bridge selector logic.
- After any submission error, inspect the composer. The bridge attempts to roll back inserted text, but rollback is best-effort if RosyTalk changed or closed the window.

### Relay works, but ChatGPT cannot see tools

The local relay and ChatGPT connection are separate phases. Follow [Connect ChatGPT](CONNECT_CHATGPT.md), keep the tunnel helper's `tunnel-client run` process alive, and restart the helper to rerun its ephemeral `doctor --explain` diagnostics. The tunnel-client's loopback `/healthz`, `/readyz`, and `/ui` surfaces are separate from the relay endpoint on port 8787.
