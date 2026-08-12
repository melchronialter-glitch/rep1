import { createServer, type Server as HttpServer } from "node:http";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import { WebSocketServer } from "ws";
import type { BridgeConfig } from "./config.js";
import { audit } from "./audit.js";
import { createRosyTalkMcpServer } from "./mcp.js";
import { LineageStore } from "./lineage.js";
import { PhoneBroker } from "./phone-broker.js";
import { MAX_PHONE_MESSAGE_BYTES } from "./protocol.js";
import { hasBearer, isLoopback } from "./security.js";

export interface RosyTalkBridgeApp {
  broker: PhoneBroker;
  httpServer: HttpServer;
  start(): Promise<{ host: string; port: number }>;
  stop(): Promise<void>;
}

function jsonRpcError(message: string) {
  return {
    jsonrpc: "2.0",
    error: { code: -32000, message },
    id: null,
  };
}

export function createRosyTalkBridgeApp(config: BridgeConfig): RosyTalkBridgeApp {
  const appOptions = config.allowedHosts
    ? { host: config.host, allowedHosts: config.allowedHosts }
    : { host: config.host };
  const app = createMcpExpressApp(appOptions);
  const httpServer = createServer(app);
  const phoneSockets = new WebSocketServer({
    noServer: true,
    maxPayload: MAX_PHONE_MESSAGE_BYTES,
  });
  const lineage = new LineageStore(config.lineageFile);
  const broker = new PhoneBroker(config.requestTimeoutMs, lineage);

  const mcpAuthorized = (request: Parameters<typeof hasBearer>[0]): boolean => {
    if (config.mcpToken && hasBearer(request, config.mcpToken)) return true;
    return (
      config.allowUnauthenticatedLocal && isLoopback(request.socket.remoteAddress)
    );
  };

  app.get("/healthz", (_request, response) => {
    const status = broker.status();
    response.json({ ok: true, phoneConnected: status.ready });
  });

  app.post("/mcp", async (request, response) => {
    if (!mcpAuthorized(request)) {
      audit({ event: "mcp.unauthorized" });
      response.setHeader("WWW-Authenticate", 'Bearer realm="aster-rosytalk-bridge"');
      response.status(401).json(jsonRpcError("Unauthorized"));
      return;
    }

    const mcpServer = createRosyTalkMcpServer(broker, lineage);
    // Omitting a session generator selects the SDK's stateless mode. The cast works
    // around an exact-optional typing mismatch inside SDK 1.30.0's Node wrapper.
    const transport = new StreamableHTTPServerTransport();
    try {
      await mcpServer.connect(transport as unknown as Transport);
      await transport.handleRequest(request, response, request.body);
      response.on("close", () => {
        void transport.close();
        void mcpServer.close();
      });
    } catch (error) {
      process.stderr.write(`MCP request failed: ${String(error)}\n`);
      if (!response.headersSent) {
        response.status(500).json(jsonRpcError("Internal server error"));
      }
    }
  });

  for (const method of ["get", "delete"] as const) {
    app[method]("/mcp", (request, response) => {
      if (!mcpAuthorized(request)) {
        response.setHeader("WWW-Authenticate", 'Bearer realm="aster-rosytalk-bridge"');
        response.status(401).json(jsonRpcError("Unauthorized"));
        return;
      }
      response.status(405).json(jsonRpcError("Method not allowed"));
    });
  }

  httpServer.on("upgrade", (request, socket, head) => {
    let pathname: string;
    try {
      pathname = new URL(request.url ?? "/", "http://localhost").pathname;
    } catch {
      socket.destroy();
      return;
    }
    if (pathname !== "/phone") {
      socket.destroy();
      return;
    }
    if (!hasBearer(request, config.phoneToken)) {
      audit({ event: "phone.rejected" });
      socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
      socket.destroy();
      return;
    }
    phoneSockets.handleUpgrade(request, socket, head, (webSocket) => {
      phoneSockets.emit("connection", webSocket, request);
    });
  });

  phoneSockets.on("connection", (socket) => broker.attach(socket));

  return {
    broker,
    httpServer,
    start: () =>
      new Promise((resolve, reject) => {
        const onError = (error: Error) => reject(error);
        httpServer.once("error", onError);
        httpServer.listen(config.port, config.host, () => {
          httpServer.off("error", onError);
          const address = httpServer.address();
          const port = typeof address === "object" && address ? address.port : config.port;
          resolve({ host: config.host, port });
        });
      }),
    stop: async () => {
      broker.close();
      for (const socket of phoneSockets.clients) socket.close(1001, "Relay stopped");
      await new Promise<void>((resolve, reject) => {
        phoneSockets.close(() => resolve());
        setTimeout(() => reject(new Error("WebSocket shutdown timed out")), 3000).unref();
      }).catch(() => undefined);
      await new Promise<void>((resolve, reject) => {
        if (!httpServer.listening) {
          resolve();
          return;
        }
        httpServer.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}
