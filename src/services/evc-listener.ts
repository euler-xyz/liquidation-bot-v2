import type { Address, Hash, Log } from 'viem';
import type { AccountStatusCheckEvent } from '../core/types';
import { getChainConfig, getConfig } from '../core/config';
import { getPublicClient, getCurrentBlock } from '../blockchain/client';
import { getEVCContract, EVC_ABI } from '../blockchain/contracts';
import { logger, createChildLogger } from '../utils/logger';
import { withRetry } from '../utils/retry';

type AccountStatusCheckLog = Log<bigint, number, false, undefined, true, typeof EVC_ABI, 'AccountStatusCheck'>;

/**
 * Callback type for account status check events.
 */
export type AccountStatusCheckCallback = (event: AccountStatusCheckEvent) => Promise<void>;

/**
 * Service for listening to EVC events on a chain.
 */
export class EVCListener {
  private chainId: number;
  private running: boolean = false;
  private lastScannedBlock: bigint = 0n;
  private onAccountStatusCheck: AccountStatusCheckCallback | null = null;
  private log: ReturnType<typeof createChildLogger>;

  constructor(chainId: number) {
    this.chainId = chainId;
    this.log = createChildLogger({ service: 'EVCListener', chainId });
  }

  /**
   * Set the callback for account status check events.
   */
  setCallback(callback: AccountStatusCheckCallback): void {
    this.onAccountStatusCheck = callback;
  }

  /**
   * Get the last scanned block number.
   */
  getLastScannedBlock(): bigint {
    return this.lastScannedBlock;
  }

  /**
   * Set the last scanned block number (for state restoration).
   */
  setLastScannedBlock(block: bigint): void {
    this.lastScannedBlock = block;
  }

  /**
   * Batch process historical logs on startup.
   */
  async batchAccountLogsOnStartup(): Promise<void> {
    const config = getConfig();
    const chainConfig = getChainConfig(this.chainId);
    const currentBlock = await getCurrentBlock(this.chainId);

    // Start from deployment block if no saved state
    if (this.lastScannedBlock === 0n) {
      this.lastScannedBlock = chainConfig.evcDeploymentBlock;
    }

    const batchSize = BigInt(config.global.monitoringParameters.batchSize);
    const batchInterval = config.global.monitoringParameters.batchInterval * 1000;

    this.log.info(
      {
        startBlock: this.lastScannedBlock.toString(),
        currentBlock: currentBlock.toString(),
        batchSize: batchSize.toString(),
      },
      'Starting historical log batch processing'
    );

    let processedEvents = 0;
    let fromBlock = this.lastScannedBlock;

    while (fromBlock < currentBlock) {
      const toBlock =
        fromBlock + batchSize > currentBlock ? currentBlock : fromBlock + batchSize;

      const events = await this.scanBlockRange(fromBlock, toBlock);
      processedEvents += events.length;

      this.lastScannedBlock = toBlock;
      fromBlock = toBlock + 1n;

      // Small delay between batches to avoid rate limiting
      if (batchInterval > 0 && fromBlock < currentBlock) {
        await new Promise((resolve) => setTimeout(resolve, batchInterval));
      }
    }

    this.log.info(
      { processedEvents, lastBlock: this.lastScannedBlock.toString() },
      'Historical log batch processing complete'
    );
  }

  /**
   * Scan a block range for AccountStatusCheck events.
   */
  async scanBlockRange(fromBlock: bigint, toBlock: bigint): Promise<AccountStatusCheckEvent[]> {
    const config = getConfig();
    const chainConfig = getChainConfig(this.chainId);
    const publicClient = getPublicClient(this.chainId);

    const events: AccountStatusCheckEvent[] = [];

    try {
      const logs = await withRetry(
        async () => {
          return publicClient.getLogs({
            address: chainConfig.contracts.EVC,
            event: {
              type: 'event',
              name: 'AccountStatusCheck',
              inputs: [
                { indexed: true, name: 'account', type: 'address' },
                { indexed: true, name: 'controller', type: 'address' },
              ],
            },
            fromBlock,
            toBlock,
          });
        },
        {
          maxRetries: config.global.apiParameters.numRetries,
          baseDelay: config.global.apiParameters.retryDelay * 1000,
          onRetry: (error, attempt) => {
            this.log.warn(
              {
                fromBlock: fromBlock.toString(),
                toBlock: toBlock.toString(),
                attempt,
                error: error.message,
              },
              'Retrying block range scan'
            );
          },
        }
      );

      for (const log of logs) {
        const event: AccountStatusCheckEvent = {
          account: log.args.account as Address,
          controller: log.args.controller as Address,
          blockNumber: log.blockNumber ?? 0n,
          transactionHash: log.transactionHash ?? ('0x' as Hash),
        };

        events.push(event);

        // Notify callback if set
        if (this.onAccountStatusCheck) {
          try {
            await this.onAccountStatusCheck(event);
          } catch (error) {
            this.log.error(
              { event, error },
              'Error in account status check callback'
            );
          }
        }
      }
    } catch (error) {
      this.log.error(
        {
          fromBlock: fromBlock.toString(),
          toBlock: toBlock.toString(),
          error,
        },
        'Failed to scan block range'
      );
      throw error;
    }

    if (events.length > 0) {
      this.log.debug(
        {
          fromBlock: fromBlock.toString(),
          toBlock: toBlock.toString(),
          eventsCount: events.length,
        },
        'Scanned block range'
      );
    }

    return events;
  }

  /**
   * Start continuous event monitoring.
   */
  async startEventMonitoring(): Promise<void> {
    if (this.running) {
      this.log.warn('Event monitoring already running');
      return;
    }

    this.running = true;
    const config = getConfig();
    const scanInterval = config.global.monitoringParameters.scanInterval * 1000;

    this.log.info({ scanInterval }, 'Starting event monitoring');

    while (this.running) {
      try {
        const currentBlock = await getCurrentBlock(this.chainId);

        if (currentBlock > this.lastScannedBlock + 1n) {
          const fromBlock = this.lastScannedBlock + 1n;
          // Stay 1 block behind to avoid reorg issues
          const toBlock = currentBlock - 1n;

          await this.scanBlockRange(fromBlock, toBlock);
          this.lastScannedBlock = toBlock;
        }
      } catch (error) {
        this.log.error({ error }, 'Error in event monitoring loop');
      }

      // Wait for next scan interval
      await new Promise((resolve) => setTimeout(resolve, scanInterval));
    }
  }

  /**
   * Stop event monitoring.
   */
  stop(): void {
    this.running = false;
    this.log.info('Event monitoring stopped');
  }

  /**
   * Check if the listener is running.
   */
  isRunning(): boolean {
    return this.running;
  }
}

// EVC listener cache per chain
const evcListenerCache = new Map<number, EVCListener>();

export function getEVCListener(chainId: number): EVCListener {
  let listener = evcListenerCache.get(chainId);
  if (!listener) {
    listener = new EVCListener(chainId);
    evcListenerCache.set(chainId, listener);
  }
  return listener;
}
