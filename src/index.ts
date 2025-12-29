import 'dotenv/config';
import { createApp } from './server/app';
import { getChainManager } from './services/chain-manager';
import { loadConfig, getSupportedChainIds } from './core/config';
import { logger } from './utils/logger';

const PORT = parseInt(process.env.PORT ?? '8080', 10);
const HOST = process.env.HOST ?? '0.0.0.0';

async function main(): Promise<void> {
  logger.info('Starting Liquidation Bot...');

  // Load configuration
  try {
    const config = loadConfig();
    logger.info(
      { chains: Array.from(config.chains.keys()) },
      'Configuration loaded'
    );
  } catch (error) {
    logger.fatal({ error }, 'Failed to load configuration');
    process.exit(1);
  }

  // Get supported chain IDs
  const chainIds = getSupportedChainIds();
  if (chainIds.length === 0) {
    logger.fatal('No chains configured');
    process.exit(1);
  }

  logger.info({ chainIds }, 'Supported chains');

  // Initialize chain manager
  const chainManager = getChainManager(chainIds);
  await chainManager.initialize();

  // Create HTTP server
  const app = await createApp();

  // Start HTTP server first so it's available immediately
  try {
    await app.listen({ port: PORT, host: HOST });
    logger.info({ port: PORT, host: HOST }, 'HTTP server listening');
  } catch (error) {
    logger.fatal({ error }, 'Failed to start HTTP server');
    process.exit(1);
  }

  // Start chain manager in the background (don't await)
  chainManager.start().then(() => {
    logger.info('Chain manager started');
  }).catch((error) => {
    logger.error({ error }, 'Chain manager failed to start');
  });

  // Graceful shutdown
  const shutdown = async (signal: string): Promise<void> => {
    logger.info({ signal }, 'Received shutdown signal');

    try {
      // Stop chain manager first
      await chainManager.stop();
      logger.info('Chain manager stopped');

      // Close HTTP server
      await app.close();
      logger.info('HTTP server closed');

      process.exit(0);
    } catch (error) {
      logger.error({ error }, 'Error during shutdown');
      process.exit(1);
    }
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));

  // Handle uncaught errors
  process.on('uncaughtException', (error) => {
    logger.fatal({ error }, 'Uncaught exception');
    process.exit(1);
  });

  process.on('unhandledRejection', (reason) => {
    logger.fatal({ reason }, 'Unhandled rejection');
    process.exit(1);
  });
}

main().catch((error) => {
  logger.fatal({ error }, 'Failed to start application');
  process.exit(1);
});
