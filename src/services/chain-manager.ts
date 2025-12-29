import { getConfig, getSupportedChainIds, getChainConfig } from '../core/config';
import { getAccountMonitor, type AccountMonitor } from './account-monitor';
import { getEVCListener, type EVCListener } from './evc-listener';
import { getStateStore } from '../persistence/state-store';
import { logger, createChildLogger } from '../utils/logger';

/**
 * Manages monitoring across multiple chains.
 */
export class ChainManager {
  private chainIds: number[];
  private monitors: Map<number, AccountMonitor> = new Map();
  private listeners: Map<number, EVCListener> = new Map();
  private running: boolean = false;
  private log: ReturnType<typeof createChildLogger>;

  constructor(chainIds?: number[]) {
    this.chainIds = chainIds ?? getSupportedChainIds();
    this.log = createChildLogger({ service: 'ChainManager' });
  }

  /**
   * Initialize all chain monitors and listeners.
   */
  async initialize(): Promise<void> {
    this.log.info({ chains: this.chainIds }, 'Initializing chain manager');

    for (const chainId of this.chainIds) {
      const chainConfig = getChainConfig(chainId);
      this.log.info({ chainId, chainName: chainConfig.name }, 'Initializing chain');

      // Create monitor and listener
      const monitor = getAccountMonitor(chainId);
      const listener = getEVCListener(chainId);

      // Connect listener to monitor
      listener.setCallback((event) => monitor.handleAccountStatusCheck(event));

      this.monitors.set(chainId, monitor);
      this.listeners.set(chainId, listener);

      // Load saved state
      const stateStore = getStateStore(chainId);
      const savedState = await stateStore.loadState();

      if (savedState) {
        listener.setLastScannedBlock(BigInt(savedState.lastScannedBlock));
        monitor.restoreQueue(
          savedState.accounts.map((a) => ({
            address: a.address as `0x${string}`,
            controllerAddress: a.controllerAddress as `0x${string}`,
            priority: a.timeOfNextUpdate,
          }))
        );
        this.log.info(
          {
            chainId,
            accountCount: savedState.accounts.length,
            lastBlock: savedState.lastScannedBlock,
          },
          'Restored saved state'
        );
      }
    }
  }

  /**
   * Start all chain monitors.
   */
  async start(): Promise<void> {
    if (this.running) {
      this.log.warn('Chain manager already running');
      return;
    }

    this.running = true;
    this.log.info('Starting chain manager');

    // Process historical logs for all chains
    await this.batchProcessHistoricalLogs();

    // Start periodic state saving
    this.startPeriodicSave();

    // Start monitors and listeners in parallel
    const promises: Promise<void>[] = [];

    for (const chainId of this.chainIds) {
      const monitor = this.monitors.get(chainId);
      const listener = this.listeners.get(chainId);

      if (monitor) {
        promises.push(
          monitor.startQueueMonitoring().catch((error) => {
            this.log.error({ chainId, error }, 'Monitor failed');
          })
        );
      }

      if (listener) {
        promises.push(
          listener.startEventMonitoring().catch((error) => {
            this.log.error({ chainId, error }, 'Listener failed');
          })
        );
      }
    }

    // Don't await - let them run in parallel
    Promise.all(promises).catch((error) => {
      this.log.error({ error }, 'Error in chain manager');
    });
  }

  /**
   * Batch process historical logs for all chains.
   */
  private async batchProcessHistoricalLogs(): Promise<void> {
    this.log.info('Processing historical logs for all chains');

    const promises = this.chainIds.map(async (chainId) => {
      const listener = this.listeners.get(chainId);
      if (listener) {
        await listener.batchAccountLogsOnStartup();
      }
    });

    await Promise.all(promises);
    this.log.info('Historical log processing complete');
  }

  /**
   * Start periodic state saving.
   */
  private startPeriodicSave(): void {
    const config = getConfig();
    const saveInterval = config.global.paths.saveInterval * 1000;

    const saveState = async (): Promise<void> => {
      if (!this.running) return;

      for (const chainId of this.chainIds) {
        try {
          await this.saveChainState(chainId);
        } catch (error) {
          this.log.error({ chainId, error }, 'Failed to save state');
        }
      }

      // Schedule next save
      setTimeout(() => {
        saveState().catch((error) => {
          this.log.error({ error }, 'Error in periodic save');
        });
      }, saveInterval);
    };

    // Start saving
    setTimeout(() => {
      saveState().catch((error) => {
        this.log.error({ error }, 'Error in periodic save');
      });
    }, saveInterval);
  }

  /**
   * Save state for a single chain.
   */
  private async saveChainState(chainId: number): Promise<void> {
    const monitor = this.monitors.get(chainId);
    const listener = this.listeners.get(chainId);
    const stateStore = getStateStore(chainId);

    if (!monitor || !listener) return;

    const accounts = monitor.getMonitoredAccounts();
    const lastScannedBlock = listener.getLastScannedBlock();

    await stateStore.saveState({
      chainId,
      lastSavedAt: Date.now(),
      lastScannedBlock: lastScannedBlock.toString(),
      accounts: accounts.map((a) => ({
        address: a.address,
        controllerAddress: a.controllerAddress,
        owner: a.owner,
        subAccountId: a.subAccountId,
        currentHealthScore: a.currentHealthScore,
        timeOfNextUpdate: a.timeOfNextUpdate,
        balance: a.balance.toString(),
        collateralValue: a.collateralValue.toString(),
        liabilityValue: a.liabilityValue.toString(),
        lastUpdated: a.lastUpdated,
      })),
      vaultAddresses: [],
    });

    this.log.debug(
      { chainId, accountCount: accounts.length, lastBlock: lastScannedBlock.toString() },
      'State saved'
    );
  }

  /**
   * Stop all chain monitors.
   */
  async stop(): Promise<void> {
    this.log.info('Stopping chain manager');
    this.running = false;

    // Stop all monitors and listeners
    for (const chainId of this.chainIds) {
      const monitor = this.monitors.get(chainId);
      const listener = this.listeners.get(chainId);

      if (monitor) {
        monitor.stop();
      }
      if (listener) {
        listener.stop();
      }

      // Save final state
      await this.saveChainState(chainId);
    }

    this.log.info('Chain manager stopped');
  }

  /**
   * Get monitor for a specific chain.
   */
  getMonitor(chainId: number): AccountMonitor | undefined {
    return this.monitors.get(chainId);
  }

  /**
   * Get listener for a specific chain.
   */
  getListener(chainId: number): EVCListener | undefined {
    return this.listeners.get(chainId);
  }

  /**
   * Get all active chain IDs.
   */
  getActiveChainIds(): number[] {
    return this.chainIds;
  }

  /**
   * Check if the manager is running.
   */
  isRunning(): boolean {
    return this.running;
  }
}

// Singleton instance
let chainManagerInstance: ChainManager | null = null;

export function getChainManager(chainIds?: number[]): ChainManager {
  if (!chainManagerInstance) {
    chainManagerInstance = new ChainManager(chainIds);
  }
  return chainManagerInstance;
}
