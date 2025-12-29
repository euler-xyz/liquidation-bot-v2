import {
  createPublicClient,
  createWalletClient,
  http,
  type PublicClient,
  type WalletClient,
  type Chain,
  type Account,
} from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { mainnet, base } from 'viem/chains';
import type { ChainConfig } from '../core/types';
import { getConfig } from '../core/config';
import { logger } from '../utils/logger';

// ============================================================================
// Custom Chain Definitions
// ============================================================================

const swell: Chain = {
  id: 1923,
  name: 'Swell',
  nativeCurrency: {
    decimals: 18,
    name: 'Ether',
    symbol: 'ETH',
  },
  rpcUrls: {
    default: { http: ['https://swell-mainnet.alt.technology'] },
  },
  blockExplorers: {
    default: { name: 'Swell Explorer', url: 'https://explorer.swellnetwork.io' },
  },
};

const sonic: Chain = {
  id: 146,
  name: 'Sonic',
  nativeCurrency: {
    decimals: 18,
    name: 'Sonic',
    symbol: 'S',
  },
  rpcUrls: {
    default: { http: ['https://rpc.soniclabs.com'] },
  },
  blockExplorers: {
    default: { name: 'Sonic Scan', url: 'https://sonicscan.org' },
  },
};

const bob: Chain = {
  id: 60808,
  name: 'BOB',
  nativeCurrency: {
    decimals: 18,
    name: 'Ether',
    symbol: 'ETH',
  },
  rpcUrls: {
    default: { http: ['https://rpc.gobob.xyz'] },
  },
  blockExplorers: {
    default: { name: 'BOB Explorer', url: 'https://explorer.gobob.xyz' },
  },
};

const berachain: Chain = {
  id: 80094,
  name: 'Berachain',
  nativeCurrency: {
    decimals: 18,
    name: 'BERA',
    symbol: 'BERA',
  },
  rpcUrls: {
    default: { http: ['https://rpc.berachain.com'] },
  },
  blockExplorers: {
    default: { name: 'Berascan', url: 'https://berascan.com' },
  },
};

const CHAINS: Record<number, Chain> = {
  1: mainnet,
  8453: base,
  1923: swell,
  146: sonic,
  60808: bob,
  80094: berachain,
};

// ============================================================================
// Client Cache
// ============================================================================

const publicClientCache = new Map<number, PublicClient>();
const walletClientCache = new Map<number, WalletClient>();
let mainnetPublicClient: PublicClient | null = null;

// ============================================================================
// Client Creation
// ============================================================================

function getChainDefinition(chainId: number): Chain {
  const chain = CHAINS[chainId];
  if (!chain) {
    throw new Error(`Unknown chain ID: ${chainId}`);
  }
  return chain;
}

export function createChainPublicClient(chainConfig: ChainConfig): PublicClient {
  const chain = getChainDefinition(chainConfig.chainId);

  return createPublicClient({
    chain: {
      ...chain,
      rpcUrls: {
        default: { http: [chainConfig.rpcUrl] },
      },
    },
    transport: http(chainConfig.rpcUrl, {
      retryCount: 3,
      retryDelay: 1000,
      timeout: 30000,
    }),
    batch: {
      multicall: true,
    },
  });
}

export function createChainWalletClient(
  chainConfig: ChainConfig,
  privateKey: `0x${string}`
): WalletClient {
  const chain = getChainDefinition(chainConfig.chainId);
  const account = privateKeyToAccount(privateKey);

  return createWalletClient({
    account,
    chain: {
      ...chain,
      rpcUrls: {
        default: { http: [chainConfig.rpcUrl] },
      },
    },
    transport: http(chainConfig.rpcUrl, {
      retryCount: 3,
      retryDelay: 1000,
      timeout: 30000,
    }),
  });
}

// ============================================================================
// Client Getters
// ============================================================================

export function getPublicClient(chainId: number): PublicClient {
  const cached = publicClientCache.get(chainId);
  if (cached) {
    return cached;
  }

  const config = getConfig();
  const chainConfig = config.chains.get(chainId);
  if (!chainConfig) {
    throw new Error(`Chain ${chainId} not configured`);
  }

  const client = createChainPublicClient(chainConfig);
  publicClientCache.set(chainId, client);

  logger.debug({ chainId, chainName: chainConfig.name }, 'Created public client');

  return client;
}

export function getWalletClient(chainId: number): WalletClient {
  const cached = walletClientCache.get(chainId);
  if (cached) {
    return cached;
  }

  const config = getConfig();
  const chainConfig = config.chains.get(chainId);
  if (!chainConfig) {
    throw new Error(`Chain ${chainId} not configured`);
  }

  const client = createChainWalletClient(chainConfig, config.liquidatorPrivateKey);
  walletClientCache.set(chainId, client);

  logger.debug({ chainId, chainName: chainConfig.name }, 'Created wallet client');

  return client;
}

export function getMainnetPublicClient(): PublicClient {
  if (mainnetPublicClient) {
    return mainnetPublicClient;
  }

  const config = getConfig();
  const mainnetConfig = config.chains.get(1);

  if (mainnetConfig) {
    mainnetPublicClient = createChainPublicClient(mainnetConfig);
  } else {
    // Fallback to public RPC
    mainnetPublicClient = createPublicClient({
      chain: mainnet,
      transport: http(),
    });
  }

  return mainnetPublicClient;
}

// ============================================================================
// Account Helpers
// ============================================================================

export function getLiquidatorAccount(): Account {
  const config = getConfig();
  return privateKeyToAccount(config.liquidatorPrivateKey);
}

export function getLiquidatorAddress(): `0x${string}` {
  return getLiquidatorAccount().address;
}

// ============================================================================
// Block Helpers
// ============================================================================

export async function getCurrentBlock(chainId: number): Promise<bigint> {
  const client = getPublicClient(chainId);
  return client.getBlockNumber();
}

export async function getGasPrice(chainId: number): Promise<bigint> {
  const client = getPublicClient(chainId);
  return client.getGasPrice();
}

// ============================================================================
// Cleanup
// ============================================================================

export function clearClientCache(): void {
  publicClientCache.clear();
  walletClientCache.clear();
  mainnetPublicClient = null;
}
