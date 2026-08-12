import { isIP } from "node:net";
import { createInterface } from "node:readline";
import { createRosyTalkBridgeApp } from "./app.js";
import { loadConfig } from "./config.js";

const HEALTH_ATTEMPTS = 20;
const HEALTH_DELAY_MS = 250;

const delay = (milliseconds: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, milliseconds));

async function verifyHealth(url: string): Promise<void> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt += 1) {
    try {
      const response = await fetch(url, {
        signal: AbortSignal.timeout(2_000),
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const body = (await response.json()) as { ok?: unknown };
      if (body.ok !== true) {
        throw new Error("health response did not contain ok=true");
      }
      return;
    } catch (error) {
      lastError = error;
      if (attempt < HEALTH_ATTEMPTS) await delay(HEALTH_DELAY_MS);
    }
  }
  throw new Error(`Health check failed: ${String(lastError)}`);
}

async function main(): Promise<void> {
  const config = loadConfig();
  const lanAddress = process.env.PHONE_LAN_ADDRESS?.trim();
  if (!lanAddress || isIP(lanAddress) !== 4) {
    throw new Error("PHONE_LAN_ADDRESS must be a valid IPv4 address");
  }

  const bridge = createRosyTalkBridgeApp(config);
  let input: ReturnType<typeof createInterface> | undefined;
  let stopping = false;
  let stopped = false;
  let stopPromise: Promise<void> | undefined;

  const stop = (reason: string): Promise<void> => {
    if (stopPromise) return stopPromise;
    if (stopping) return Promise.resolve();
    stopping = true;
    stopPromise = (async () => {
      input?.close();
      process.stdout.write(`\nStopping relay (${reason})...\n`);
      try {
        await bridge.stop();
        process.stdout.write("Relay stopped cleanly.\n");
      } catch (error) {
        process.stderr.write(
          `Relay shutdown error: ${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 1;
      } finally {
        stopped = true;
      }
    })();
    return stopPromise;
  };

  process.once("SIGINT", () => void stop("Ctrl+C"));
  process.once("SIGTERM", () => void stop("termination request"));

  try {
    const address = await bridge.start();
    const healthUrl = `http://127.0.0.1:${address.port}/healthz`;
    await verifyHealth(healthUrl);

    process.stdout.write(
      "\nREADY FOR THE PHONE — /healthz verified\n" +
        "Phase 1 only: the phone-to-laptop relay is running. ChatGPT is not connected yet.\n\n" +
        `Relay WebSocket URL:\n  ws://${lanAddress}:${address.port}/phone\n` +
        `Phone browser test:\n  http://${lanAddress}:${address.port}/healthz\n` +
        `Phone token:\n  ${config.phoneToken}\n\n` +
        "Keep the token local; do not paste it into ChatGPT.\n" +
        "In the Android app, select only the RosyTalk target app, enable its accessibility service, and tap Connect.\n" +
        "Message submission remains OFF until you enable its per-session switch on the phone.\n" +
        "Keep this window open. Type STOP and press Enter, or press Ctrl+C, to stop the relay.\n\n",
    );

    const consoleInput = createInterface({ input: process.stdin, output: process.stdout });
    input = consoleInput;
    consoleInput.setPrompt("relay> ");
    consoleInput.prompt();
    consoleInput.on("line", (line) => {
      if (line.trim().toUpperCase() === "STOP") {
        void stop("STOP command");
        return;
      }
      process.stdout.write("Type STOP and press Enter to stop the relay.\n");
      consoleInput.prompt();
    });
    consoleInput.on("close", () => {
      if (!stopping && !stopped) void stop("console input closed");
    });

    await new Promise<void>((resolve) => {
      const poll = setInterval(() => {
        if (stopped) {
          clearInterval(poll);
          resolve();
        }
      }, 100);
    });
  } catch (error) {
    await stop("startup failure").catch(() => undefined);
    throw error;
  }
}

main().catch((error) => {
  process.stderr.write(
    `Relay startup failed: ${error instanceof Error ? error.message : String(error)}\n`,
  );
  process.exitCode = 1;
});
