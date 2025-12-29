import type { Address } from 'viem';
import type { AccountStatusCheckEvent, QueueItem } from '../core/types';
import { PriorityQueue } from '../core/priority-queue';
import { getAccount, getCachedAccountsForChain, type Account } from '../core/account';
import { getVault } from '../core/vault';
import { getConfig, getChainConfig } from '../core/config';
import { getOracleHandler } from './oracle-handler';
import { getLiquidator } from './liquidator';
import { getNotifier } from './notifier';
import { logger, createChildLogger } from '../utils/logger';
import { INFINITE_HEALTH_SCORE } from '../utils/constants';

/**
 * Service for monitoring account health and triggering liquidations.
 */
export class AccountMonitor {
  private chainId: number;
  private queue: PriorityQueue;
  private running: boolean = false;
  private seenAccounts: Set<string> = new Set();
  private executeLiquidations: boolean = true;
  private log: ReturnType<typeof createChildLogger>;

  constructor(chainId: number, executeLiquidations: boolean = true) {
    this.chainId = chainId;
    this.queue = new PriorityQueue();
    this.executeLiquidations = executeLiquidations;
    this.log = createChildLogger({ service: 'AccountMonitor', chainId });
  }

  /**
   * Get the priority queue.
   */
  getQueue(): PriorityQueue {
    return this.queue;
  }

  /**
   * Get the number of monitored accounts.
   */
  getAccountCount(): number {
    return this.seenAccounts.size;
  }

  /**
   * Set whether to execute liquidations or just simulate.
   */
  setExecuteLiquidations(execute: boolean): void {
    this.executeLiquidations = execute;
  }

  /**
   * Handle an AccountStatusCheck event.
   */
  async handleAccountStatusCheck(event: AccountStatusCheckEvent): Promise<void> {
    const accountKey = `${event.account.toLowerCase()}:${event.controller.toLowerCase()}`;

    // Get or create account
    const account = getAccount(this.chainId, event.account, event.controller);

    // Initialize vault if needed
    const vault = getVault(this.chainId, event.controller);
    await vault.initialize();

    // Resolve Pyth feed IDs if not cached
    if (vault.isPythFeedIdsCacheStale(getConfig().global.pythCacheRefresh * 1000)) {
      const oracleHandler = getOracleHandler();
      await oracleHandler.getFeedIds(this.chainId, vault);
    }

    // Update account liquidity
    await account.updateLiquidity();

    // Add to seen accounts
    const isNew = !this.seenAccounts.has(accountKey);
    this.seenAccounts.add(accountKey);

    // Schedule for monitoring if account has liability
    if (account.hasBorrow()) {
      this.queue.push({
        address: account.address,
        controllerAddress: account.controllerAddress,
        priority: account.timeOfNextUpdate,
      });

      if (isNew) {
        this.log.debug(
          {
            account: account.address,
            controller: account.controllerAddress,
            healthScore: account.currentHealthScore,
          },
          'New account added to monitoring'
        );
      }
    }

    // Check if unhealthy and process immediately
    if (account.isUnhealthy()) {
      await this.processUnhealthyAccount(account);
    }
  }

  /**
   * Process an unhealthy account.
   */
  private async processUnhealthyAccount(account: Account): Promise<void> {
    const notifier = getNotifier();
    const vaultInfo = await account.vault.getInfo();

    // Send notification if appropriate
    if (account.shouldReport()) {
      account.markReported();
      await notifier.notifyLowHealth(
        this.chainId,
        account.address,
        account.controllerAddress,
        vaultInfo.name,
        account.currentHealthScore,
        Number(account.liabilityValue) / 1e18
      );
    }

    // Simulate liquidation
    const liquidator = getLiquidator(this.chainId);
    const result = await liquidator.simulateLiquidation(account);

    if (result.isProfitable && result.data) {
      // Notify about opportunity
      await notifier.notifyOpportunity(
        this.chainId,
        account.address,
        vaultInfo.name,
        result.data.collateralSymbol,
        result.data.borrowedSymbol,
        Number(result.data.netProfitEth) / 1e18
      );

      // Execute if enabled
      if (this.executeLiquidations) {
        try {
          await liquidator.executeLiquidation(result.data);
        } catch (error) {
          this.log.error(
            { account: account.address, error },
            'Failed to execute liquidation'
          );
          await notifier.notifyError(
            this.chainId,
            'LIQUIDATION_EXECUTION',
            (error as Error).message,
            { account: account.address }
          );
        }
      }
    }
  }

  /**
   * Start the queue monitoring loop.
   */
  async startQueueMonitoring(): Promise<void> {
    if (this.running) {
      this.log.warn('Queue monitoring already running');
      return;
    }

    this.running = true;
    this.log.info('Starting queue monitoring');

    while (this.running) {
      try {
        await this.processQueueIteration();
      } catch (error) {
        this.log.error({ error }, 'Error in queue monitoring loop');
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    }
  }

  /**
   * Process one iteration of the queue.
   */
  private async processQueueIteration(): Promise<void> {
    const now = Math.floor(Date.now() / 1000);

    // Get all due items
    const dueItems = this.queue.getDueItems(now);

    if (dueItems.length === 0) {
      // Wait a bit before checking again
      const nextItem = this.queue.peek();
      if (nextItem) {
        const waitTime = Math.max(0, (nextItem.priority - now) * 1000);
        await new Promise((resolve) => setTimeout(resolve, Math.min(waitTime, 10000)));
      } else {
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      return;
    }

    // Process due accounts in parallel (with limit)
    const batchSize = 10;
    for (let i = 0; i < dueItems.length; i += batchSize) {
      const batch = dueItems.slice(i, i + batchSize);
      await Promise.all(batch.map((item) => this.updateAccountLiquidity(item)));
    }
  }

  /**
   * Update account liquidity and reschedule.
   */
  private async updateAccountLiquidity(item: QueueItem): Promise<void> {
    try {
      const account = getAccount(this.chainId, item.address, item.controllerAddress);

      // Update liquidity
      await account.updateLiquidity();

      // Check if unhealthy
      if (account.isUnhealthy()) {
        await this.processUnhealthyAccount(account);
      }

      // Reschedule if still has liability
      if (account.hasBorrow()) {
        this.queue.push({
          address: account.address,
          controllerAddress: account.controllerAddress,
          priority: account.timeOfNextUpdate,
        });
      }
    } catch (error) {
      this.log.error(
        {
          account: item.address,
          controller: item.controllerAddress,
          error,
        },
        'Failed to update account liquidity'
      );

      // Reschedule for later
      const config = getConfig();
      const retryDelay = config.global.reportingParameters.errorCooldown;
      this.queue.push({
        address: item.address,
        controllerAddress: item.controllerAddress,
        priority: Math.floor(Date.now() / 1000) + retryDelay,
      });
    }
  }

  /**
   * Stop the queue monitoring loop.
   */
  stop(): void {
    this.running = false;
    this.log.info('Queue monitoring stopped');
  }

  /**
   * Check if the monitor is running.
   */
  isRunning(): boolean {
    return this.running;
  }

  /**
   * Get all monitored accounts sorted by health score.
   */
  getMonitoredAccounts(): Account[] {
    return getCachedAccountsForChain(this.chainId)
      .filter((account) => account.hasBorrow() && account.currentHealthScore < INFINITE_HEALTH_SCORE)
      .sort((a, b) => a.currentHealthScore - b.currentHealthScore);
  }

  /**
   * Restore queue from saved state.
   */
  restoreQueue(items: QueueItem[]): void {
    this.queue.fromArray(items);

    for (const item of items) {
      const accountKey = `${item.address.toLowerCase()}:${item.controllerAddress.toLowerCase()}`;
      this.seenAccounts.add(accountKey);
    }

    this.log.info(
      { itemCount: items.length },
      'Restored queue from saved state'
    );
  }

  /**
   * Get queue items for persistence.
   */
  getQueueItems(): QueueItem[] {
    return this.queue.toArray();
  }
}

// Account monitor cache per chain
const accountMonitorCache = new Map<number, AccountMonitor>();

export function getAccountMonitor(chainId: number, executeLiquidations?: boolean): AccountMonitor {
  let monitor = accountMonitorCache.get(chainId);
  if (!monitor) {
    monitor = new AccountMonitor(chainId, executeLiquidations);
    accountMonitorCache.set(chainId, monitor);
  }
  return monitor;
}
