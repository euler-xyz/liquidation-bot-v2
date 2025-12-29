import type { FastifyPluginAsync } from 'fastify';
import type { AllPositionsResponse, PositionResponse } from '../../core/types';
import { getChainManager } from '../../services/chain-manager';
import { INFINITE_HEALTH_SCORE } from '../../utils/constants';

interface PositionsQuerystring {
  chainId?: string;
}

export const positionsRoutes: FastifyPluginAsync = async (app) => {
  app.get<{
    Querystring: PositionsQuerystring;
    Reply: AllPositionsResponse | { error: string };
  }>(
    '/allPositions',
    {
      schema: {
        tags: ['liquidation'],
        summary: 'Get all monitored positions',
        description:
          'Returns all positions being monitored, sorted by health score (lowest first)',
        querystring: {
          type: 'object',
          properties: {
            chainId: {
              type: 'string',
              description: 'Chain ID to filter positions (e.g., 1 for Ethereum mainnet)',
            },
          },
        },
        response: {
          200: {
            type: 'object',
            properties: {
              chainId: { type: 'number' },
              positions: {
                type: 'array',
                items: {
                  type: 'object',
                  properties: {
                    address: { type: 'string' },
                    owner: { type: 'string' },
                    subaccount: { type: 'number' },
                    healthScore: { type: 'number' },
                    valueBorrowed: { type: 'string' },
                    vaultName: { type: 'string' },
                    vaultAddress: { type: 'string' },
                  },
                },
              },
              timestamp: { type: 'number' },
            },
          },
          400: {
            type: 'object',
            properties: {
              error: { type: 'string' },
            },
          },
        },
      },
    },
    async (request, reply) => {
      const { chainId: chainIdStr } = request.query;

      if (!chainIdStr) {
        reply.status(400);
        return { error: 'chainId query parameter is required' };
      }

      const chainId = parseInt(chainIdStr, 10);
      if (isNaN(chainId)) {
        reply.status(400);
        return { error: 'Invalid chainId' };
      }

      const chainManager = getChainManager();
      const monitor = chainManager.getMonitor(chainId);

      if (!monitor) {
        reply.status(400);
        return { error: `Chain ${chainId} is not being monitored` };
      }

      const accounts = monitor.getMonitoredAccounts();

      const positions: PositionResponse[] = await Promise.all(
        accounts
          .filter((account) => account.currentHealthScore < INFINITE_HEALTH_SCORE)
          .map(async (account) => {
            const vaultInfo = await account.vault.getInfo();

            return {
              address: account.address,
              owner: account.owner,
              subaccount: account.subAccountId,
              healthScore: account.currentHealthScore,
              valueBorrowed: account.liabilityValue.toString(),
              vaultName: vaultInfo.name,
              vaultAddress: account.controllerAddress,
            };
          })
      );

      return {
        chainId,
        positions,
        timestamp: Date.now(),
      };
    }
  );

  app.get<{
    Reply: { chains: number[] };
  }>(
    '/chains',
    {
      schema: {
        tags: ['liquidation'],
        summary: 'Get active chains',
        description: 'Returns list of chain IDs being monitored',
        response: {
          200: {
            type: 'object',
            properties: {
              chains: {
                type: 'array',
                items: { type: 'number' },
              },
            },
          },
        },
      },
    },
    async () => {
      const chainManager = getChainManager();
      return {
        chains: chainManager.getActiveChainIds(),
      };
    }
  );

  app.get<{
    Querystring: PositionsQuerystring;
    Reply: {
      chainId: number;
      totalAccounts: number;
      unhealthyAccounts: number;
      highRiskAccounts: number;
    } | { error: string };
  }>(
    '/stats',
    {
      schema: {
        tags: ['liquidation'],
        summary: 'Get monitoring statistics',
        description: 'Returns statistics about monitored accounts',
        querystring: {
          type: 'object',
          properties: {
            chainId: {
              type: 'string',
              description: 'Chain ID',
            },
          },
        },
        response: {
          200: {
            type: 'object',
            properties: {
              chainId: { type: 'number' },
              totalAccounts: { type: 'number' },
              unhealthyAccounts: { type: 'number' },
              highRiskAccounts: { type: 'number' },
            },
          },
          400: {
            type: 'object',
            properties: {
              error: { type: 'string' },
            },
          },
        },
      },
    },
    async (request, reply) => {
      const { chainId: chainIdStr } = request.query;

      if (!chainIdStr) {
        reply.status(400);
        return { error: 'chainId query parameter is required' };
      }

      const chainId = parseInt(chainIdStr, 10);
      if (isNaN(chainId)) {
        reply.status(400);
        return { error: 'Invalid chainId' };
      }

      const chainManager = getChainManager();
      const monitor = chainManager.getMonitor(chainId);

      if (!monitor) {
        reply.status(400);
        return { error: `Chain ${chainId} is not being monitored` };
      }

      const accounts = monitor.getMonitoredAccounts();

      return {
        chainId,
        totalAccounts: accounts.length,
        unhealthyAccounts: accounts.filter((a) => a.isUnhealthy()).length,
        highRiskAccounts: accounts.filter((a) => a.isHighRisk()).length,
      };
    }
  );
};
