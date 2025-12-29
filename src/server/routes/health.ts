import type { FastifyPluginAsync } from 'fastify';
import { getChainManager } from '../../services/chain-manager';

interface HealthResponse {
  status: 'ok' | 'error';
  timestamp: string;
  uptime: number;
  chains: {
    chainId: number;
    name: string;
    running: boolean;
    accountCount: number;
    lastBlock: string;
  }[];
}

export const healthRoutes: FastifyPluginAsync = async (app) => {
  app.get<{
    Reply: HealthResponse;
  }>(
    '/health',
    {
      schema: {
        tags: ['health'],
        summary: 'Health check endpoint',
        description: 'Returns the health status of the liquidation bot',
        response: {
          200: {
            type: 'object',
            properties: {
              status: { type: 'string', enum: ['ok', 'error'] },
              timestamp: { type: 'string', format: 'date-time' },
              uptime: { type: 'number' },
              chains: {
                type: 'array',
                items: {
                  type: 'object',
                  properties: {
                    chainId: { type: 'number' },
                    name: { type: 'string' },
                    running: { type: 'boolean' },
                    accountCount: { type: 'number' },
                    lastBlock: { type: 'string' },
                  },
                },
              },
            },
          },
        },
      },
    },
    async () => {
      const chainManager = getChainManager();
      const chainIds = chainManager.getActiveChainIds();

      const chains = chainIds.map((chainId) => {
        const monitor = chainManager.getMonitor(chainId);
        const listener = chainManager.getListener(chainId);

        return {
          chainId,
          name: `Chain ${chainId}`,
          running: monitor?.isRunning() ?? false,
          accountCount: monitor?.getAccountCount() ?? 0,
          lastBlock: listener?.getLastScannedBlock().toString() ?? '0',
        };
      });

      return {
        status: 'ok',
        timestamp: new Date().toISOString(),
        uptime: process.uptime(),
        chains,
      };
    }
  );

  app.get(
    '/',
    {
      schema: {
        tags: ['health'],
        summary: 'Root endpoint',
        description: 'Simple health check',
        response: {
          200: {
            type: 'object',
            properties: {
              status: { type: 'string' },
              message: { type: 'string' },
            },
          },
        },
      },
    },
    async () => {
      return {
        status: 'ok',
        message: 'Liquidation Bot is running',
      };
    }
  );
};
