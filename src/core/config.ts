import { z } from 'zod';
import { parse as parseYaml } from 'yaml';
import { readFileSync } from 'fs';
import { join } from 'path';
import type { Address, Hex } from 'viem';
import type {
  AppConfig,
  ChainConfig,
  GlobalConfig,
  RiskParameters,
  PositionSizeThresholds,
  UpdateIntervals,
  ReportingParameters,
  MonitoringParameters,
  ApiParameters,
  PathConfig,
  ChainContracts,
} from './types';

// ============================================================================
// Zod Schemas
// ============================================================================

const addressSchema = z.string().regex(/^0x[a-fA-F0-9]{40}$/) as z.ZodType<Address>;
const hexSchema = z.string().regex(/^0x[a-fA-F0-9]+$/) as z.ZodType<Hex>;

const chainContractsSchema = z.object({
  LIQUIDATOR_CONTRACT: addressSchema,
  EVC: addressSchema,
  SWAPPER: addressSchema,
  SWAP_VERIFIER: addressSchema,
  WETH: addressSchema,
  USD: addressSchema,
  BTC: addressSchema,
  PYTH: z.string(), // Can be empty for some chains
});

const chainConfigSchema = z.object({
  name: z.string(),
  EVC_DEPLOYMENT_BLOCK: z.number(),
  EXPLORER_URL: z.string().url(),
  RPC_NAME: z.string(),
  contracts: chainContractsSchema,
});

const globalConfigSchema = z.object({
  // Risk Parameters
  HS_LIQUIDATION: z.number(),
  HS_HIGH_RISK: z.number(),
  HS_SAFE: z.number(),

  // Position Size Thresholds
  TEENY: z.number(),
  MINI: z.number(),
  SMALL: z.number(),
  MEDIUM: z.number(),

  // Update Intervals
  TEENY_LIQ: z.number(),
  TEENY_HIGH: z.number(),
  TEENY_LOW: z.number(),
  TEENY_SAFE: z.number(),
  MINI_LIQ: z.number(),
  MINI_HIGH: z.number(),
  MINI_LOW: z.number(),
  MINI_SAFE: z.number(),
  SMALL_LIQ: z.number(),
  SMALL_HIGH: z.number(),
  SMALL_LOW: z.number(),
  SMALL_SAFE: z.number(),
  MEDIUM_LIQ: z.number(),
  MEDIUM_HIGH: z.number(),
  MEDIUM_LOW: z.number(),
  MEDIUM_SAFE: z.number(),
  LARGE_LIQ: z.number(),
  LARGE_HIGH: z.number(),
  LARGE_LOW: z.number(),
  LARGE_SAFE: z.number(),

  // Reporting Parameters
  LOW_HEALTH_REPORT_INTERVAL: z.number(),
  SLACK_REPORT_HEALTH_SCORE: z.number(),
  BORROW_VALUE_THRESHOLD: z.number(),
  SMALL_POSITION_THRESHOLD: z.number(),
  SMALL_POSITION_REPORT_INTERVAL: z.number(),
  ERROR_COOLDOWN: z.number(),

  // Monitoring Parameters
  BATCH_SIZE: z.number(),
  BATCH_INTERVAL: z.number(),
  SCAN_INTERVAL: z.number(),

  // Paths
  EVAULT_ABI_PATH: z.string(),
  EVC_ABI_PATH: z.string(),
  LIQUIDATOR_ABI_PATH: z.string(),
  ORACLE_ABI_PATH: z.string(),
  PYTH_ABI_PATH: z.string(),
  ERC20_ABI_PATH: z.string(),
  ROUTER_ABI_PATH: z.string(),
  LOGS_PATH: z.string(),
  SAVE_STATE_PATH: z.string(),
  SAVE_INTERVAL: z.number(),

  // API Parameters
  NUM_RETRIES: z.number(),
  RETRY_DELAY: z.number(),
  API_REQUEST_DELAY: z.number(),
  SWAP_SLIPPAGE: z.number(),
  SWAP_DEADLINE: z.number(),

  // Pyth
  PYTH_CACHE_REFRESH: z.number(),

  // Profit Receiver
  PROFIT_RECEIVER: addressSchema,

  // Mainnet specific
  MAINNET_ETH_ADAPTER: addressSchema,
  MAINNET_ETH_ADDRESS: addressSchema,
  MAINNET_BTC_ADAPTER: addressSchema,

  // Legacy fields (optional)
  MIN_UPDATE_INTERVAL_SMALL: z.number().optional(),
  HIGH_RISK_UPDATE_INTERVAL: z.number().optional(),
  MAX_UPDATE_INTERVAL: z.number().optional(),
});

const configFileSchema = z.object({
  global: globalConfigSchema,
  chains: z.record(z.string(), chainConfigSchema),
});

const envSchema = z.object({
  LIQUIDATOR_EOA: addressSchema,
  LIQUIDATOR_PRIVATE_KEY: hexSchema,
  SWAP_API_URL: z.string().url(),
  SLACK_WEBHOOK_URL: z.string().url().optional(),
  RISK_DASHBOARD_URL: z.string().url().optional(),
  // RPC URLs - RPC_URL is used as fallback for MAINNET_RPC_URL
  RPC_URL: z.string().url().optional(),
  MAINNET_RPC_URL: z.string().url().optional(),
  BASE_RPC_URL: z.string().url().optional(),
  SWELL_RPC_URL: z.string().url().optional(),
  SONIC_RPC_URL: z.string().url().optional(),
  BOB_RPC_URL: z.string().url().optional(),
  BERA_RPC_URL: z.string().url().optional(),
});

// ============================================================================
// Configuration Parser
// ============================================================================

function parseGlobalConfig(raw: z.infer<typeof globalConfigSchema>): GlobalConfig {
  const riskParameters: RiskParameters = {
    hsLiquidation: raw.HS_LIQUIDATION,
    hsHighRisk: raw.HS_HIGH_RISK,
    hsSafe: raw.HS_SAFE,
  };

  const positionSizeThresholds: PositionSizeThresholds = {
    teeny: BigInt(raw.TEENY),
    mini: BigInt(raw.MINI),
    small: BigInt(raw.SMALL),
    medium: BigInt(raw.MEDIUM),
  };

  const updateIntervals: UpdateIntervals = {
    teenyLiq: raw.TEENY_LIQ,
    teenyHigh: raw.TEENY_HIGH,
    teenyLow: raw.TEENY_LOW,
    teenySafe: raw.TEENY_SAFE,
    miniLiq: raw.MINI_LIQ,
    miniHigh: raw.MINI_HIGH,
    miniLow: raw.MINI_LOW,
    miniSafe: raw.MINI_SAFE,
    smallLiq: raw.SMALL_LIQ,
    smallHigh: raw.SMALL_HIGH,
    smallLow: raw.SMALL_LOW,
    smallSafe: raw.SMALL_SAFE,
    mediumLiq: raw.MEDIUM_LIQ,
    mediumHigh: raw.MEDIUM_HIGH,
    mediumLow: raw.MEDIUM_LOW,
    mediumSafe: raw.MEDIUM_SAFE,
    largeLiq: raw.LARGE_LIQ,
    largeHigh: raw.LARGE_HIGH,
    largeLow: raw.LARGE_LOW,
    largeSafe: raw.LARGE_SAFE,
  };

  const reportingParameters: ReportingParameters = {
    lowHealthReportInterval: raw.LOW_HEALTH_REPORT_INTERVAL,
    slackReportHealthScore: raw.SLACK_REPORT_HEALTH_SCORE,
    borrowValueThreshold: raw.BORROW_VALUE_THRESHOLD,
    smallPositionThreshold: BigInt(raw.SMALL_POSITION_THRESHOLD),
    smallPositionReportInterval: raw.SMALL_POSITION_REPORT_INTERVAL,
    errorCooldown: raw.ERROR_COOLDOWN,
  };

  const monitoringParameters: MonitoringParameters = {
    batchSize: raw.BATCH_SIZE,
    batchInterval: raw.BATCH_INTERVAL,
    scanInterval: raw.SCAN_INTERVAL,
  };

  const apiParameters: ApiParameters = {
    numRetries: raw.NUM_RETRIES,
    retryDelay: raw.RETRY_DELAY,
    apiRequestDelay: raw.API_REQUEST_DELAY,
    swapSlippage: raw.SWAP_SLIPPAGE,
    swapDeadline: raw.SWAP_DEADLINE,
  };

  const paths: PathConfig = {
    evaultAbiPath: raw.EVAULT_ABI_PATH,
    evcAbiPath: raw.EVC_ABI_PATH,
    liquidatorAbiPath: raw.LIQUIDATOR_ABI_PATH,
    oracleAbiPath: raw.ORACLE_ABI_PATH,
    pythAbiPath: raw.PYTH_ABI_PATH,
    erc20AbiPath: raw.ERC20_ABI_PATH,
    routerAbiPath: raw.ROUTER_ABI_PATH,
    logsPath: raw.LOGS_PATH,
    saveStatePath: raw.SAVE_STATE_PATH,
    saveInterval: raw.SAVE_INTERVAL,
  };

  return {
    riskParameters,
    positionSizeThresholds,
    updateIntervals,
    reportingParameters,
    monitoringParameters,
    apiParameters,
    paths,
    pythCacheRefresh: raw.PYTH_CACHE_REFRESH,
    profitReceiver: raw.PROFIT_RECEIVER,
    mainnetEthAdapter: raw.MAINNET_ETH_ADAPTER,
    mainnetEthAddress: raw.MAINNET_ETH_ADDRESS,
    mainnetBtcAdapter: raw.MAINNET_BTC_ADAPTER,
  };
}

function parseChainConfig(
  chainId: number,
  raw: z.infer<typeof chainConfigSchema>,
  env: z.infer<typeof envSchema>
): ChainConfig {
  const rpcName = raw.RPC_NAME as keyof typeof env;
  let rpcUrl = env[rpcName];

  // Use RPC_URL as fallback for mainnet
  if (!rpcUrl && rpcName === 'MAINNET_RPC_URL' && env.RPC_URL) {
    rpcUrl = env.RPC_URL;
  }

  if (!rpcUrl) {
    throw new Error(`RPC URL not found for chain ${chainId} (expected env var: ${raw.RPC_NAME})`);
  }

  const contracts: ChainContracts = {
    LIQUIDATOR_CONTRACT: raw.contracts.LIQUIDATOR_CONTRACT as Address,
    EVC: raw.contracts.EVC as Address,
    SWAPPER: raw.contracts.SWAPPER as Address,
    SWAP_VERIFIER: raw.contracts.SWAP_VERIFIER as Address,
    WETH: raw.contracts.WETH as Address,
    USD: raw.contracts.USD as Address,
    BTC: raw.contracts.BTC as Address,
    PYTH: (raw.contracts.PYTH || '0x0000000000000000000000000000000000000000') as Address,
  };

  return {
    chainId,
    name: raw.name,
    evcDeploymentBlock: BigInt(raw.EVC_DEPLOYMENT_BLOCK),
    explorerUrl: raw.EXPLORER_URL,
    rpcName: raw.RPC_NAME,
    rpcUrl,
    contracts,
  };
}

// ============================================================================
// Configuration Loader
// ============================================================================

export function loadConfig(configPath?: string): AppConfig {
  // Load environment variables
  const envResult = envSchema.safeParse(process.env);
  if (!envResult.success) {
    throw new Error(`Invalid environment variables: ${envResult.error.message}`);
  }
  const env = envResult.data;

  // Load and parse YAML config
  const configFilePath = configPath ?? join(process.cwd(), 'app', 'config.yaml');
  const configContent = readFileSync(configFilePath, 'utf-8');
  const rawConfig = parseYaml(configContent);

  const configResult = configFileSchema.safeParse(rawConfig);
  if (!configResult.success) {
    throw new Error(`Invalid config file: ${configResult.error.message}`);
  }

  const parsedConfig = configResult.data;

  // Parse global config
  const globalConfig = parseGlobalConfig(parsedConfig.global);

  // Parse chain configs
  const chains = new Map<number, ChainConfig>();
  for (const [chainIdStr, chainRaw] of Object.entries(parsedConfig.chains)) {
    const chainId = parseInt(chainIdStr, 10);
    try {
      const chainConfig = parseChainConfig(chainId, chainRaw, env);
      chains.set(chainId, chainConfig);
    } catch (error) {
      // Skip chains without RPC URLs configured
      console.warn(`Skipping chain ${chainId}: ${(error as Error).message}`);
    }
  }

  if (chains.size === 0) {
    throw new Error('No chains configured with valid RPC URLs');
  }

  return {
    global: globalConfig,
    chains,
    liquidatorEoa: env.LIQUIDATOR_EOA,
    liquidatorPrivateKey: env.LIQUIDATOR_PRIVATE_KEY,
    swapApiUrl: env.SWAP_API_URL,
    slackWebhookUrl: env.SLACK_WEBHOOK_URL,
    riskDashboardUrl: env.RISK_DASHBOARD_URL,
  };
}

// ============================================================================
// Configuration Singleton
// ============================================================================

let configInstance: AppConfig | null = null;

export function getConfig(): AppConfig {
  if (!configInstance) {
    configInstance = loadConfig();
  }
  return configInstance;
}

export function resetConfig(): void {
  configInstance = null;
}

// ============================================================================
// Chain Config Helpers
// ============================================================================

export function getChainConfig(chainId: number): ChainConfig {
  const config = getConfig();
  const chainConfig = config.chains.get(chainId);
  if (!chainConfig) {
    throw new Error(`Chain ${chainId} not configured`);
  }
  return chainConfig;
}

export function getSupportedChainIds(): number[] {
  const config = getConfig();
  return Array.from(config.chains.keys());
}
