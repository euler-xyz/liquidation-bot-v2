import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import type { SavedState } from '../core/types';
import { getConfig, getChainConfig } from '../core/config';
import { logger, createChildLogger } from '../utils/logger';

/**
 * Service for persisting and restoring bot state.
 */
export class StateStore {
  private chainId: number;
  private statePath: string;
  private log: ReturnType<typeof createChildLogger>;

  constructor(chainId: number) {
    this.chainId = chainId;
    const config = getConfig();
    const chainConfig = getChainConfig(chainId);

    // Construct state file path
    const stateDir = config.global.paths.saveStatePath;
    const fileName = `${chainConfig.name.toLowerCase()}_state.json`;
    this.statePath = join(process.cwd(), stateDir, fileName);

    this.log = createChildLogger({ service: 'StateStore', chainId });

    // Ensure state directory exists
    const dir = dirname(this.statePath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
  }

  /**
   * Save state to disk.
   */
  async saveState(state: SavedState): Promise<void> {
    try {
      const json = JSON.stringify(state, null, 2);
      writeFileSync(this.statePath, json, 'utf-8');

      this.log.debug(
        {
          path: this.statePath,
          accountCount: state.accounts.length,
        },
        'State saved'
      );
    } catch (error) {
      this.log.error({ error, path: this.statePath }, 'Failed to save state');
      throw error;
    }
  }

  /**
   * Load state from disk.
   */
  async loadState(): Promise<SavedState | null> {
    try {
      if (!existsSync(this.statePath)) {
        this.log.debug({ path: this.statePath }, 'No saved state found');
        return null;
      }

      const json = readFileSync(this.statePath, 'utf-8');
      const state = JSON.parse(json) as SavedState;

      this.log.info(
        {
          path: this.statePath,
          accountCount: state.accounts.length,
          lastSavedAt: new Date(state.lastSavedAt).toISOString(),
        },
        'State loaded'
      );

      return state;
    } catch (error) {
      this.log.error({ error, path: this.statePath }, 'Failed to load state');
      return null;
    }
  }

  /**
   * Delete saved state.
   */
  async deleteState(): Promise<void> {
    try {
      if (existsSync(this.statePath)) {
        const { unlinkSync } = await import('fs');
        unlinkSync(this.statePath);
        this.log.info({ path: this.statePath }, 'State deleted');
      }
    } catch (error) {
      this.log.error({ error, path: this.statePath }, 'Failed to delete state');
      throw error;
    }
  }

  /**
   * Get the state file path.
   */
  getStatePath(): string {
    return this.statePath;
  }

  /**
   * Check if state file exists.
   */
  hasState(): boolean {
    return existsSync(this.statePath);
  }
}

// State store cache per chain
const stateStoreCache = new Map<number, StateStore>();

export function getStateStore(chainId: number): StateStore {
  let store = stateStoreCache.get(chainId);
  if (!store) {
    store = new StateStore(chainId);
    stateStoreCache.set(chainId, store);
  }
  return store;
}
