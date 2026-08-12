# Windows launchers

- `Start-Aster-RosyTalk-Bridge.cmd` is the normal one-click launcher. It generates/reuses separate phone and MCP secrets, installs locked Node dependencies, builds the relay, and starts it.
- `Start-Aster-RosyTalk-Tunnel.cmd` is an optional helper for an already-created OpenAI Secure MCP Tunnel. It never downloads `tunnel-client`, creates credentials, or installs a ChatGPT connection.
- `Build-Windows-Bundle.ps1` creates a clean distributable zip while excluding all local `.env` variants, package-manager credentials, signing/private-key material, dependencies, build output, logs, `tunnel-client.exe`, and prior archives. It copies back only the inert `.env.example` template and scans the staged tree before compression. If a local debug APK was built, it copies that APK into the staged `release` folder without packaging the rest of Gradle's output.

Start with [Windows setup](../docs/SETUP_WINDOWS.md), then read [Connect ChatGPT](../docs/CONNECT_CHATGPT.md) only if the local phone bridge is working.
