import { createRosyTalkBridgeApp } from "./app.js";
import { loadConfig } from "./config.js";
import { existsSync, rmSync, writeFileSync } from "node:fs";

const stopFile = process.env.ASTER_RELAY_STOP_FILE?.trim();
const pidFile = process.env.ASTER_RELAY_PID_FILE?.trim();

async function main(): Promise<void> {
  const config = loadConfig();
  const bridge = createRosyTalkBridgeApp(config);
  const address = await bridge.start();
  process.stderr.write(
    `Aster RosyTalk Bridge listening on http://${address.host}:${address.port}\n` +
      `MCP: /mcp  Android WebSocket: /phone\n`,
  );

  if (pidFile) {
    writeFileSync(pidFile, `${process.pid}\n`, { encoding: "utf8", mode: 0o600 });
  }

  let shuttingDown = false;
  let stopFileTimer: NodeJS.Timeout | undefined;
  const shutdown = async () => {
    if (shuttingDown) return;
    shuttingDown = true;
    if (stopFileTimer) clearInterval(stopFileTimer);
    process.stderr.write("Stopping Aster RosyTalk Bridge\n");
    try {
      await bridge.stop();
    } finally {
      if (pidFile) rmSync(pidFile, { force: true });
      if (stopFile) rmSync(stopFile, { force: true });
    }
  };
  process.once("SIGINT", () => void shutdown().then(() => process.exit(0)));
  process.once("SIGTERM", () => void shutdown().then(() => process.exit(0)));

  if (stopFile) {
    rmSync(stopFile, { force: true });
    stopFileTimer = setInterval(() => {
      if (!existsSync(stopFile)) return;
      void shutdown().then(() => process.exit(0));
    }, 250);
    stopFileTimer.unref();
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exit(1);
});
