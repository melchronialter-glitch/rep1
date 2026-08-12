import { z } from "zod";

const knownPlaceholderTokens = new Set([
  "replace-with-phone-secret",
  "replace-with-mcp-client-secret",
]);

const envSchema = z.object({
  HOST: z.string().default("127.0.0.1"),
  PORT: z.coerce.number().int().min(0).max(65535).default(8787),
  PHONE_TOKEN: z.string().min(20),
  MCP_TOKEN: z.string().min(20).optional(),
  MCP_ALLOW_UNAUTHENTICATED_LOCAL: z
    .enum(["true", "false"])
    .default("false")
    .transform((value) => value === "true"),
  REQUEST_TIMEOUT_MS: z.coerce.number().int().min(1000).max(120000).default(15000),
  ALLOWED_HOSTS: z.string().optional(),
  LINEAGE_FILE: z.string().min(1).max(4096).default(".aster-runtime/rosytalk-lineage.jsonl"),
});

export interface BridgeConfig {
  host: string;
  port: number;
  phoneToken: string;
  mcpToken: string | undefined;
  allowUnauthenticatedLocal: boolean;
  requestTimeoutMs: number;
  allowedHosts: string[] | undefined;
  lineageFile: string;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): BridgeConfig {
  const parsed = envSchema.parse(env);
  if (knownPlaceholderTokens.has(parsed.PHONE_TOKEN)) {
    throw new Error("PHONE_TOKEN must be replaced with a random secret");
  }
  if (parsed.MCP_TOKEN && knownPlaceholderTokens.has(parsed.MCP_TOKEN)) {
    throw new Error("MCP_TOKEN must be replaced with a random secret");
  }
  if (parsed.MCP_TOKEN === parsed.PHONE_TOKEN) {
    throw new Error("PHONE_TOKEN and MCP_TOKEN must be different secrets");
  }
  if (!parsed.MCP_TOKEN && !parsed.MCP_ALLOW_UNAUTHENTICATED_LOCAL) {
    throw new Error(
      "MCP_TOKEN is required unless MCP_ALLOW_UNAUTHENTICATED_LOCAL=true",
    );
  }

  const allowedHosts = parsed.ALLOWED_HOSTS
    ?.split(",")
    .map((host) => host.trim())
    .filter(Boolean);

  return {
    host: parsed.HOST,
    port: parsed.PORT,
    phoneToken: parsed.PHONE_TOKEN,
    mcpToken: parsed.MCP_TOKEN,
    allowUnauthenticatedLocal: parsed.MCP_ALLOW_UNAUTHENTICATED_LOCAL,
    requestTimeoutMs: parsed.REQUEST_TIMEOUT_MS,
    allowedHosts: allowedHosts?.length ? allowedHosts : undefined,
    lineageFile: parsed.LINEAGE_FILE,
  };
}
