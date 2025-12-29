import type { Address } from 'viem';
import type {
  AccountState,
  AccountLiquidity,
  HealthCategory,
  PositionSize,
  GlobalConfig,
} from './types';
import { getVault, type Vault } from './vault';
import { getConfig } from './config';
import { INFINITE_HEALTH_SCORE, USD_ADDRESS, BTC_ADDRESS } from '../utils/constants';
import { logger } from '../utils/logger';

/**
 * Represents an account (borrower) with positions in the Euler protocol.
 * Tracks health score and determines optimal update scheduling.
 */
export class Account {
  readonly chainId: number;
  readonly address: Address;
  readonly controllerAddress: Address;
  readonly owner: Address;
  readonly subAccountId: number;

  private _vault: Vault;
  private _currentHealthScore: number = INFINITE_HEALTH_SCORE;
  private _timeOfNextUpdate: number = 0;
  private _balance: bigint = 0n;
  private _collateralValue: bigint = 0n;
  private _liabilityValue: bigint = 0n;
  private _lastUpdated: number = 0;
  private _lastReportedAt: number = 0;

  constructor(
    chainId: number,
    address: Address,
    controllerAddress: Address
  ) {
    this.chainId = chainId;
    this.address = address;
    this.controllerAddress = controllerAddress;

    // Parse owner and subaccount from the address
    // The account address encodes the owner and subaccount ID
    this.owner = `0x${address.slice(2, 42)}` as Address;
    this.subAccountId = parseInt(address.slice(42), 16);

    this._vault = getVault(chainId, controllerAddress);
  }

  // ============================================================================
  // Getters
  // ============================================================================

  get vault(): Vault {
    return this._vault;
  }

  get currentHealthScore(): number {
    return this._currentHealthScore;
  }

  get timeOfNextUpdate(): number {
    return this._timeOfNextUpdate;
  }

  get balance(): bigint {
    return this._balance;
  }

  get collateralValue(): bigint {
    return this._collateralValue;
  }

  get liabilityValue(): bigint {
    return this._liabilityValue;
  }

  get lastUpdated(): number {
    return this._lastUpdated;
  }

  get lastReportedAt(): number {
    return this._lastReportedAt;
  }

  // ============================================================================
  // State Updates
  // ============================================================================

  /**
   * Update account liquidity and health score.
   */
  async updateLiquidity(): Promise<void> {
    const liquidity = await this._vault.getAccountLiquidity(this.address);

    this._balance = liquidity.balance;
    this._collateralValue = liquidity.collateralValue;
    this._liabilityValue = liquidity.liabilityValue;
    this._lastUpdated = Date.now();

    // Calculate health score
    this._currentHealthScore = this.calculateHealthScore(
      liquidity.collateralValue,
      liquidity.liabilityValue
    );

    // Calculate next update time
    this._timeOfNextUpdate = this.calculateTimeOfNextUpdate();

    logger.debug(
      {
        chainId: this.chainId,
        account: this.address,
        healthScore: this._currentHealthScore,
        nextUpdate: new Date(this._timeOfNextUpdate * 1000).toISOString(),
      },
      'Account liquidity updated'
    );
  }

  /**
   * Calculate health score from collateral and liability values.
   */
  private calculateHealthScore(collateralValue: bigint, liabilityValue: bigint): number {
    if (liabilityValue === 0n) {
      return INFINITE_HEALTH_SCORE;
    }

    // Get vault info for unit of account handling
    const vaultInfo = this._vault['_info'];
    if (!vaultInfo) {
      // Vault not initialized, return simple calculation
      return Number(collateralValue) / Number(liabilityValue);
    }

    // For ETH and BTC units of account on mainnet, we may need conversion
    // For now, use direct division as the Python code does this inline
    return Number(collateralValue) / Number(liabilityValue);
  }

  /**
   * Calculate the optimal time for the next update based on health score and position size.
   */
  private calculateTimeOfNextUpdate(): number {
    const config = getConfig();
    const global = config.global;

    const healthScore = this._currentHealthScore;
    const liabilityValue = this._liabilityValue;

    // Determine position size category
    const positionSize = this.getPositionSize(liabilityValue, global);

    // Determine health category
    const healthCategory = this.getHealthCategory(healthScore, global);

    // Get base interval based on position size and health category
    const baseInterval = this.getUpdateInterval(positionSize, healthCategory, global);

    // Apply ±10% random variance to prevent thundering herd
    const variance = 0.9 + Math.random() * 0.2;
    const interval = Math.floor(baseInterval * variance);

    // Calculate next update timestamp
    const now = Math.floor(Date.now() / 1000);
    return now + interval;
  }

  /**
   * Determine position size category based on liability value.
   */
  private getPositionSize(liabilityValue: bigint, config: GlobalConfig): PositionSize {
    const thresholds = config.positionSizeThresholds;

    if (liabilityValue < thresholds.teeny) {
      return 'teeny';
    } else if (liabilityValue < thresholds.mini) {
      return 'mini';
    } else if (liabilityValue < thresholds.small) {
      return 'small';
    } else if (liabilityValue < thresholds.medium) {
      return 'medium';
    } else {
      return 'large';
    }
  }

  /**
   * Determine health category based on health score.
   */
  private getHealthCategory(healthScore: number, config: GlobalConfig): HealthCategory {
    const params = config.riskParameters;

    if (healthScore < params.hsLiquidation) {
      return 'liquidation';
    } else if (healthScore < params.hsHighRisk) {
      return 'high_risk';
    } else if (healthScore < params.hsSafe) {
      return 'low_risk';
    } else {
      return 'safe';
    }
  }

  /**
   * Get update interval based on position size and health category.
   */
  private getUpdateInterval(
    positionSize: PositionSize,
    healthCategory: HealthCategory,
    config: GlobalConfig
  ): number {
    const intervals = config.updateIntervals;

    const key = `${positionSize}${this.healthCategoryToSuffix(healthCategory)}` as keyof typeof intervals;

    return intervals[key] ?? intervals.largeSafe;
  }

  private healthCategoryToSuffix(category: HealthCategory): string {
    switch (category) {
      case 'liquidation':
        return 'Liq';
      case 'high_risk':
        return 'High';
      case 'low_risk':
        return 'Low';
      case 'safe':
        return 'Safe';
    }
  }

  // ============================================================================
  // Health Status
  // ============================================================================

  /**
   * Check if account is unhealthy (can be liquidated).
   */
  isUnhealthy(): boolean {
    const config = getConfig();
    return this._currentHealthScore < config.global.riskParameters.hsLiquidation;
  }

  /**
   * Check if account is at high risk.
   */
  isHighRisk(): boolean {
    const config = getConfig();
    const params = config.global.riskParameters;
    return (
      this._currentHealthScore >= params.hsLiquidation &&
      this._currentHealthScore < params.hsHighRisk
    );
  }

  /**
   * Check if account has any liability (is a borrower).
   */
  hasBorrow(): boolean {
    return this._liabilityValue > 0n;
  }

  /**
   * Check if account should be reported to Slack.
   */
  shouldReport(): boolean {
    const config = getConfig();
    const reporting = config.global.reportingParameters;

    // Check if health score is low enough to report
    if (this._currentHealthScore > reporting.slackReportHealthScore) {
      return false;
    }

    // Check if position is large enough
    if (this._liabilityValue < BigInt(reporting.borrowValueThreshold) * 10n ** 18n) {
      return false;
    }

    // Check if enough time has passed since last report
    const now = Date.now();
    const timeSinceLastReport = (now - this._lastReportedAt) / 1000;

    if (this._liabilityValue < reporting.smallPositionThreshold) {
      return timeSinceLastReport >= reporting.smallPositionReportInterval;
    }

    return timeSinceLastReport >= reporting.lowHealthReportInterval;
  }

  /**
   * Mark account as reported.
   */
  markReported(): void {
    this._lastReportedAt = Date.now();
  }

  // ============================================================================
  // Serialization
  // ============================================================================

  /**
   * Convert to state object for persistence.
   */
  toState(): AccountState {
    return {
      address: this.address,
      controllerAddress: this.controllerAddress,
      owner: this.owner,
      subAccountId: this.subAccountId,
      currentHealthScore: this._currentHealthScore,
      timeOfNextUpdate: this._timeOfNextUpdate,
      balance: this._balance,
      collateralValue: this._collateralValue,
      liabilityValue: this._liabilityValue,
      lastUpdated: this._lastUpdated,
    };
  }

  /**
   * Restore state from persistence.
   */
  restoreState(state: AccountState): void {
    this._currentHealthScore = state.currentHealthScore;
    this._timeOfNextUpdate = state.timeOfNextUpdate;
    this._balance = state.balance;
    this._collateralValue = state.collateralValue;
    this._liabilityValue = state.liabilityValue;
    this._lastUpdated = state.lastUpdated;
  }
}

// ============================================================================
// Account Cache
// ============================================================================

const accountCache = new Map<string, Account>();

function getAccountKey(chainId: number, address: Address, controllerAddress: Address): string {
  return `${chainId}:${address.toLowerCase()}:${controllerAddress.toLowerCase()}`;
}

/**
 * Get or create an Account instance.
 */
export function getAccount(
  chainId: number,
  address: Address,
  controllerAddress: Address
): Account {
  const key = getAccountKey(chainId, address, controllerAddress);
  let account = accountCache.get(key);

  if (!account) {
    account = new Account(chainId, address, controllerAddress);
    accountCache.set(key, account);
  }

  return account;
}

/**
 * Get a cached Account instance if it exists.
 */
export function getCachedAccount(
  chainId: number,
  address: Address,
  controllerAddress: Address
): Account | undefined {
  const key = getAccountKey(chainId, address, controllerAddress);
  return accountCache.get(key);
}

/**
 * Get all cached accounts for a chain.
 */
export function getCachedAccountsForChain(chainId: number): Account[] {
  const accounts: Account[] = [];
  for (const [key, account] of accountCache) {
    if (key.startsWith(`${chainId}:`)) {
      accounts.push(account);
    }
  }
  return accounts;
}

/**
 * Clear the account cache.
 */
export function clearAccountCache(): void {
  accountCache.clear();
}

/**
 * Remove an account from the cache.
 */
export function removeAccountFromCache(
  chainId: number,
  address: Address,
  controllerAddress: Address
): boolean {
  const key = getAccountKey(chainId, address, controllerAddress);
  return accountCache.delete(key);
}
