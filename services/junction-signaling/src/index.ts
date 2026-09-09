// Entrypoint: config -> logger -> server -> listen -> signal handlers.

import { loadConfig, ConfigError } from "./config.js";
import { createLogger } from "./logger.js";
import { createJunctionServer, listen } from "./server.js";

function main(): void {
  let config;
  try {
    config = loadConfig();
  } catch (err) {
    if (err instanceof ConfigError) {
      // eslint-disable-next-line no-console
      console.error(`[junction-signaling] configuration error: ${err.message}`);
      process.exit(1);
    }
    throw err;
  }

  const logger = createLogger({ level: config.logLevel });
  const server = createJunctionServer(config, logger);

  listen(server, config.port, config.host).then(() => {
    const addr = server.address();
    logger.info("server.listening", { host: addr.host, port: addr.port });
  });

  let shuttingDown = false;
  async function handleSignal(signal: string): Promise<void> {
    if (shuttingDown) return;
    shuttingDown = true;
    logger.info("server.shutdown_signal", { signal });
    try {
      await server.shutdown();
      logger.info("server.shutdown_complete", {});
      process.exit(0);
    } catch (err) {
      logger.error("server.shutdown_error", {
        message: err instanceof Error ? err.message : String(err),
      });
      process.exit(1);
    }
  }

  process.on("SIGTERM", () => void handleSignal("SIGTERM"));
  process.on("SIGINT", () => void handleSignal("SIGINT"));
}

main();
