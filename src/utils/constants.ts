import type { Address } from 'viem';

// ============================================================================
// Chain IDs
// ============================================================================

export const CHAIN_IDS = {
  ETHEREUM: 1,
  BASE: 8453,
  SWELL: 1923,
  SONIC: 146,
  BOB: 60808,
  BERACHAIN: 80094,
} as const;

export type SupportedChainId = (typeof CHAIN_IDS)[keyof typeof CHAIN_IDS];

// ============================================================================
// Well-known Addresses
// ============================================================================

export const ZERO_ADDRESS: Address = '0x0000000000000000000000000000000000000000';

export const USD_ADDRESS: Address = '0x0000000000000000000000000000000000000348';

export const BTC_ADDRESS: Address = '0xbBbBBBBbbBBBbbbBbbBbbbbBBbBbbbbBbBbbBBbB';

// ============================================================================
// Oracle Names
// ============================================================================

export const ORACLE_NAMES = {
  PYTH: 'PythOracle',
  CROSS_ADAPTER: 'CrossAdapter',
  CHAINLINK: 'ChainlinkOracle',
} as const;

// ============================================================================
// Time Constants
// ============================================================================

export const SECONDS = {
  MINUTE: 60,
  HOUR: 3600,
  DAY: 86400,
  WEEK: 604800,
} as const;

// ============================================================================
// Pyth Network
// ============================================================================

export const PYTH_HERMES_URL = 'https://hermes.pyth.network/v2/updates/price/latest';

// ============================================================================
// Default Decimals
// ============================================================================

export const DEFAULT_DECIMALS = 18;

// ============================================================================
// Health Score Infinity Representation
// ============================================================================

export const INFINITE_HEALTH_SCORE = Number.MAX_SAFE_INTEGER;

// ============================================================================
// Gas Buffer Multiplier
// ============================================================================

export const GAS_PRICE_BUFFER = 1.2; // 20% buffer on gas price

// ============================================================================
// Swap API
// ============================================================================

export const SWAP_AMOUNT_MULTIPLIER = 0.999; // Use 99.9% of seized collateral for swap
