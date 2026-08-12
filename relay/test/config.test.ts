import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadConfig } from "../src/config.js";

const validEnvironment: NodeJS.ProcessEnv = {
  PHONE_TOKEN: "p".repeat(32),
  MCP_TOKEN: "m".repeat(32),
};

describe("relay configuration security invariants", () => {
  test("uses authenticated boundaries and bounded request defaults", () => {
    const config = loadConfig(validEnvironment);
    assert.equal(config.host, "127.0.0.1");
    assert.equal(config.allowUnauthenticatedLocal, false);
    assert.equal(config.requestTimeoutMs, 15_000);
  });

  test("rejects credentials shared across phone and MCP boundaries", () => {
    const shared = "s".repeat(32);
    assert.throws(
      () => loadConfig({ PHONE_TOKEN: shared, MCP_TOKEN: shared }),
      /must be different secrets/,
    );
  });

  test("rejects public example credential sentinels", () => {
    assert.throws(
      () =>
        loadConfig({
          PHONE_TOKEN: "replace-with-phone-secret",
          MCP_TOKEN: validEnvironment.MCP_TOKEN,
        }),
      /PHONE_TOKEN must be replaced/,
    );
    assert.throws(
      () =>
        loadConfig({
          PHONE_TOKEN: validEnvironment.PHONE_TOKEN,
          MCP_TOKEN: "replace-with-mcp-client-secret",
        }),
      /MCP_TOKEN must be replaced/,
    );
  });
});
