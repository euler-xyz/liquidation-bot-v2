import type { Address, Hex } from 'viem';
import type { VaultInfo, AccountLiquidity, LiquidationCheck } from './types';
import {
  getEVaultContract,
  getAssetInfo,
  getVaultAsset,
  getVaultOracle,
  getVaultUnitOfAccount,
} from '../blockchain/contracts';
import { getLiquidatorAddress } from '../blockchain/client';
import { logger } from '../utils/logger';

/**
 * Represents an EVault in the EVK system.
 * Provides methods for querying account liquidity and liquidation parameters.
 */
export class Vault {
  readonly chainId: number;
  readonly address: Address;

  private _info: VaultInfo | null = null;
  private _pythFeedIds: Set<Hex> = new Set();
  private _pythFeedIdsCachedAt: number = 0;

  constructor(chainId: number, address: Address) {
    this.chainId = chainId;
    this.address = address;
  }

  /**
   * Initialize vault info by fetching from the blockchain.
   */
  async initialize(): Promise<VaultInfo> {
    if (this._info) {
      return this._info;
    }

    const contract = getEVaultContract(this.chainId, this.address);

    const [asset, oracle, unitOfAccount, name] = await Promise.all([
      getVaultAsset(this.chainId, this.address),
      getVaultOracle(this.chainId, this.address),
      getVaultUnitOfAccount(this.chainId, this.address),
      contract.read.name() as Promise<string>,
    ]);

    const assetInfo = await getAssetInfo(this.chainId, asset);

    this._info = {
      address: this.address,
      asset,
      assetSymbol: assetInfo.symbol,
      assetDecimals: assetInfo.decimals,
      name,
      oracle,
      unitOfAccount,
      pythFeedIds: this._pythFeedIds,
    };

    logger.debug(
      { chainId: this.chainId, vault: this.address, asset: assetInfo.symbol },
      'Vault initialized'
    );

    return this._info;
  }

  /**
   * Get vault info, initializing if necessary.
   */
  async getInfo(): Promise<VaultInfo> {
    if (!this._info) {
      return this.initialize();
    }
    return this._info;
  }

  /**
   * Get account liquidity (balance, collateral value, liability value).
   */
  async getAccountLiquidity(accountAddress: Address): Promise<AccountLiquidity> {
    const contract = getEVaultContract(this.chainId, this.address);

    const [balance, liquidityResult] = await Promise.all([
      contract.read.balanceOf([accountAddress]) as Promise<bigint>,
      contract.read.accountLiquidity([accountAddress, true]) as Promise<[bigint, bigint]>,
    ]);

    return {
      balance,
      collateralValue: liquidityResult[0],
      liabilityValue: liquidityResult[1],
    };
  }

  /**
   * Check liquidation parameters for a violator account.
   */
  async checkLiquidation(
    violatorAddress: Address,
    collateralVaultAddress: Address
  ): Promise<LiquidationCheck> {
    const contract = getEVaultContract(this.chainId, this.address);
    const liquidatorAddress = getLiquidatorAddress();

    const result = await contract.read.checkLiquidation([
      liquidatorAddress,
      violatorAddress,
      collateralVaultAddress,
    ]) as [bigint, bigint];

    return {
      maxRepay: result[0],
      seizedCollateralShares: result[1],
    };
  }

  /**
   * Convert vault shares to underlying assets.
   */
  async convertToAssets(shares: bigint): Promise<bigint> {
    const contract = getEVaultContract(this.chainId, this.address);
    return contract.read.convertToAssets([shares]) as Promise<bigint>;
  }

  /**
   * Get list of acceptable collateral vaults (LTV list).
   */
  async getLtvList(): Promise<Address[]> {
    const contract = getEVaultContract(this.chainId, this.address);
    return contract.read.LTVList() as Promise<Address[]>;
  }

  /**
   * Set Pyth feed IDs for this vault.
   */
  setPythFeedIds(feedIds: Set<Hex>): void {
    this._pythFeedIds = feedIds;
    this._pythFeedIdsCachedAt = Date.now();
    if (this._info) {
      this._info.pythFeedIds = feedIds;
    }
  }

  /**
   * Get Pyth feed IDs for this vault.
   */
  getPythFeedIds(): Set<Hex> {
    return this._pythFeedIds;
  }

  /**
   * Check if Pyth feed IDs cache is stale.
   */
  isPythFeedIdsCacheStale(maxAgeMs: number): boolean {
    return Date.now() - this._pythFeedIdsCachedAt > maxAgeMs;
  }

  /**
   * Check if this vault uses Pyth oracle.
   */
  hasPythOracle(): boolean {
    return this._pythFeedIds.size > 0;
  }
}

// ============================================================================
// Vault Cache
// ============================================================================

const vaultCache = new Map<string, Vault>();

function getVaultKey(chainId: number, address: Address): string {
  return `${chainId}:${address.toLowerCase()}`;
}

/**
 * Get or create a Vault instance.
 */
export function getVault(chainId: number, address: Address): Vault {
  const key = getVaultKey(chainId, address);
  let vault = vaultCache.get(key);

  if (!vault) {
    vault = new Vault(chainId, address);
    vaultCache.set(key, vault);
  }

  return vault;
}

/**
 * Get a cached Vault instance if it exists.
 */
export function getCachedVault(chainId: number, address: Address): Vault | undefined {
  const key = getVaultKey(chainId, address);
  return vaultCache.get(key);
}

/**
 * Clear the vault cache.
 */
export function clearVaultCache(): void {
  vaultCache.clear();
}

/**
 * Get all cached vaults for a chain.
 */
export function getCachedVaultsForChain(chainId: number): Vault[] {
  const vaults: Vault[] = [];
  for (const [key, vault] of vaultCache) {
    if (key.startsWith(`${chainId}:`)) {
      vaults.push(vault);
    }
  }
  return vaults;
}
