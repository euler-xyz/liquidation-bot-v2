import type { Address, Hex } from 'viem';
import { getConfig, getChainConfig } from '../core/config';
import { getOracleContract, getPythContract } from '../blockchain/contracts';
import { getPublicClient } from '../blockchain/client';
import { type Vault, getVault } from '../core/vault';
import { ORACLE_NAMES, PYTH_HERMES_URL } from '../utils/constants';
import { withRetry } from '../utils/retry';
import { logger } from '../utils/logger';

interface PythHermesResponse {
  binary: {
    data: string[];
  };
}

/**
 * Service for handling Pyth oracle integration.
 */
export class OracleHandler {
  private feedIdCache: Map<string, Set<Hex>> = new Map();
  private feedIdCacheTimestamps: Map<string, number> = new Map();

  /**
   * Get Pyth feed IDs for a vault's oracle configuration.
   */
  async getFeedIds(chainId: number, vault: Vault): Promise<Set<Hex>> {
    const config = getConfig();
    const cacheKey = `${chainId}:${vault.address}`;

    // Check cache
    const cachedFeedIds = this.feedIdCache.get(cacheKey);
    const cachedAt = this.feedIdCacheTimestamps.get(cacheKey) ?? 0;
    const cacheMaxAge = config.global.pythCacheRefresh * 1000;

    if (cachedFeedIds && Date.now() - cachedAt < cacheMaxAge) {
      return cachedFeedIds;
    }

    // Get vault info
    const vaultInfo = await vault.getInfo();

    // Resolve feed IDs from oracle configuration
    const feedIds = await this.resolveFeedIds(
      chainId,
      vaultInfo.oracle,
      vaultInfo.asset,
      vaultInfo.unitOfAccount
    );

    // Also check collateral vaults
    const ltvList = await vault.getLtvList();
    for (const collateralVaultAddress of ltvList) {
      const collateralVault = getVault(chainId, collateralVaultAddress);
      const collateralInfo = await collateralVault.getInfo();

      const collateralFeedIds = await this.resolveFeedIds(
        chainId,
        collateralInfo.oracle,
        collateralInfo.asset,
        vaultInfo.unitOfAccount
      );

      for (const feedId of collateralFeedIds) {
        feedIds.add(feedId);
      }
    }

    // Update cache
    this.feedIdCache.set(cacheKey, feedIds);
    this.feedIdCacheTimestamps.set(cacheKey, Date.now());

    // Update vault's feed IDs
    vault.setPythFeedIds(feedIds);

    logger.debug(
      { chainId, vault: vault.address, feedIds: Array.from(feedIds) },
      'Resolved Pyth feed IDs'
    );

    return feedIds;
  }

  /**
   * Recursively resolve Pyth feed IDs from an oracle configuration.
   */
  private async resolveFeedIds(
    chainId: number,
    oracleAddress: Address,
    asset: Address,
    unitOfAccount: Address
  ): Promise<Set<Hex>> {
    const feedIds = new Set<Hex>();

    try {
      const oracle = getOracleContract(chainId, oracleAddress);

      // Try to resolve the oracle configuration
      const result = await oracle.read.resolveOracle([0n, asset, unitOfAccount]) as [
        bigint,
        Address,
        Address,
        Address
      ];

      const configuredOracleAddress = result[3];

      if (configuredOracleAddress === '0x0000000000000000000000000000000000000000') {
        return feedIds;
      }

      // Get the oracle name
      const configuredOracle = getOracleContract(chainId, configuredOracleAddress);
      const oracleName = await configuredOracle.read.name() as string;

      if (oracleName === ORACLE_NAMES.PYTH) {
        // This is a Pyth oracle, get its feed ID
        const feedId = await configuredOracle.read.feedId() as Hex;
        feedIds.add(feedId);
      } else if (oracleName === ORACLE_NAMES.CROSS_ADAPTER) {
        // This is a cross adapter, resolve its nested oracles
        const nestedFeedIds = await this.resolveCrossAdapterFeedIds(
          chainId,
          configuredOracleAddress
        );
        for (const feedId of nestedFeedIds) {
          feedIds.add(feedId);
        }
      }
    } catch (error) {
      logger.debug(
        { chainId, oracleAddress, asset, error },
        'Failed to resolve feed IDs'
      );
    }

    return feedIds;
  }

  /**
   * Resolve Pyth feed IDs from a CrossAdapter oracle.
   */
  private async resolveCrossAdapterFeedIds(
    chainId: number,
    crossAdapterAddress: Address
  ): Promise<Set<Hex>> {
    const feedIds = new Set<Hex>();

    try {
      const crossAdapter = getOracleContract(chainId, crossAdapterAddress);

      // Get base and cross oracles from the adapter
      const baseOracle = await crossAdapter.read.base() as Address;
      const crossOracle = await crossAdapter.read.cross() as Address;

      // Check base oracle
      const baseOracleName = await this.getOracleName(chainId, baseOracle);
      if (baseOracleName === ORACLE_NAMES.PYTH) {
        const baseFeedId = await this.getPythFeedId(chainId, baseOracle);
        if (baseFeedId) {
          feedIds.add(baseFeedId);
        }
      } else if (baseOracleName === ORACLE_NAMES.CROSS_ADAPTER) {
        const nestedFeedIds = await this.resolveCrossAdapterFeedIds(chainId, baseOracle);
        for (const feedId of nestedFeedIds) {
          feedIds.add(feedId);
        }
      }

      // Check cross oracle
      const crossOracleName = await this.getOracleName(chainId, crossOracle);
      if (crossOracleName === ORACLE_NAMES.PYTH) {
        const crossFeedId = await this.getPythFeedId(chainId, crossOracle);
        if (crossFeedId) {
          feedIds.add(crossFeedId);
        }
      } else if (crossOracleName === ORACLE_NAMES.CROSS_ADAPTER) {
        const nestedFeedIds = await this.resolveCrossAdapterFeedIds(chainId, crossOracle);
        for (const feedId of nestedFeedIds) {
          feedIds.add(feedId);
        }
      }
    } catch (error) {
      logger.debug(
        { chainId, crossAdapterAddress, error },
        'Failed to resolve cross adapter feed IDs'
      );
    }

    return feedIds;
  }

  /**
   * Get the name of an oracle contract.
   */
  private async getOracleName(chainId: number, oracleAddress: Address): Promise<string> {
    try {
      const oracle = getOracleContract(chainId, oracleAddress);
      return await oracle.read.name() as string;
    } catch {
      return '';
    }
  }

  /**
   * Get the Pyth feed ID from a Pyth oracle contract.
   */
  private async getPythFeedId(chainId: number, pythOracleAddress: Address): Promise<Hex | null> {
    try {
      const oracle = getOracleContract(chainId, pythOracleAddress);
      return await oracle.read.feedId() as Hex;
    } catch {
      return null;
    }
  }

  /**
   * Fetch latest price update data from Pyth Hermes API.
   */
  async getPythUpdateData(feedIds: Set<Hex> | Hex[]): Promise<Hex> {
    const feedIdArray = Array.isArray(feedIds) ? feedIds : Array.from(feedIds);

    if (feedIdArray.length === 0) {
      throw new Error('No feed IDs provided');
    }

    const queryParams = feedIdArray.map((id) => `ids[]=${id}`).join('&');
    const url = `${PYTH_HERMES_URL}?${queryParams}`;

    const response = await withRetry(
      async () => {
        const res = await fetch(url);
        if (!res.ok) {
          throw new Error(`Pyth Hermes API error: ${res.status}`);
        }
        return res.json() as Promise<PythHermesResponse>;
      },
      {
        maxRetries: 3,
        baseDelay: 1000,
      }
    );

    const data = response.binary.data[0];
    if (!data) {
      throw new Error('No update data received from Pyth');
    }

    return `0x${data}` as Hex;
  }

  /**
   * Get the fee required to submit a Pyth update.
   */
  async getPythUpdateFee(chainId: number, updateData: Hex): Promise<bigint> {
    const pythContract = getPythContract(chainId);
    if (!pythContract) {
      return 0n;
    }

    return pythContract.read.getUpdateFee([[updateData]]) as Promise<bigint>;
  }

  /**
   * Check if a chain has Pyth oracle support.
   */
  hasPythSupport(chainId: number): boolean {
    const chainConfig = getChainConfig(chainId);
    return (
      !!chainConfig.contracts.PYTH &&
      chainConfig.contracts.PYTH !== '0x0000000000000000000000000000000000000000'
    );
  }

  /**
   * Clear the feed ID cache.
   */
  clearCache(): void {
    this.feedIdCache.clear();
    this.feedIdCacheTimestamps.clear();
  }
}

// Singleton instance
let oracleHandlerInstance: OracleHandler | null = null;

export function getOracleHandler(): OracleHandler {
  if (!oracleHandlerInstance) {
    oracleHandlerInstance = new OracleHandler();
  }
  return oracleHandlerInstance;
}
