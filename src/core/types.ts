import type { Address, Hash, Hex } from 'viem';

// ============================================================================
// Chain Configuration Types
// ============================================================================

export interface ChainContracts {
  LIQUIDATOR_CONTRACT: Address;
  EVC: Address;
  SWAPPER: Address;
  SWAP_VERIFIER: Address;
  WETH: Address;
  USD: Address;
  BTC: Address;
  PYTH: Address;
}

export interface ChainConfig {
  chainId: number;
  name: string;
  evcDeploymentBlock: bigint;
  explorerUrl: string;
  rpcName: string;
  rpcUrl: string;
  contracts: ChainContracts;
}

// ============================================================================
// Global Configuration Types
// ============================================================================

export interface RiskParameters {
  hsLiquidation: number;
  hsHighRisk: number;
  hsSafe: number;
}

export interface PositionSizeThresholds {
  teeny: bigint;
  mini: bigint;
  small: bigint;
  medium: bigint;
}

export interface UpdateIntervals {
  teenyLiq: number;
  teenyHigh: number;
  teenyLow: number;
  teenySafe: number;
  miniLiq: number;
  miniHigh: number;
  miniLow: number;
  miniSafe: number;
  smallLiq: number;
  smallHigh: number;
  smallLow: number;
  smallSafe: number;
  mediumLiq: number;
  mediumHigh: number;
  mediumLow: number;
  mediumSafe: number;
  largeLiq: number;
  largeHigh: number;
  largeLow: number;
  largeSafe: number;
}

export interface ReportingParameters {
  lowHealthReportInterval: number;
  slackReportHealthScore: number;
  borrowValueThreshold: number;
  smallPositionThreshold: bigint;
  smallPositionReportInterval: number;
  errorCooldown: number;
}

export interface MonitoringParameters {
  batchSize: number;
  batchInterval: number;
  scanInterval: number;
}

export interface ApiParameters {
  numRetries: number;
  retryDelay: number;
  apiRequestDelay: number;
  swapSlippage: number;
  swapDeadline: number;
}

export interface PathConfig {
  evaultAbiPath: string;
  evcAbiPath: string;
  liquidatorAbiPath: string;
  oracleAbiPath: string;
  pythAbiPath: string;
  erc20AbiPath: string;
  routerAbiPath: string;
  logsPath: string;
  saveStatePath: string;
  saveInterval: number;
}

export interface GlobalConfig {
  riskParameters: RiskParameters;
  positionSizeThresholds: PositionSizeThresholds;
  updateIntervals: UpdateIntervals;
  reportingParameters: ReportingParameters;
  monitoringParameters: MonitoringParameters;
  apiParameters: ApiParameters;
  paths: PathConfig;
  pythCacheRefresh: number;
  profitReceiver: Address;
  mainnetEthAdapter: Address;
  mainnetEthAddress: Address;
  mainnetBtcAdapter: Address;
}

export interface AppConfig {
  global: GlobalConfig;
  chains: Map<number, ChainConfig>;
  liquidatorEoa: Address;
  liquidatorPrivateKey: Hex;
  swapApiUrl: string;
  slackWebhookUrl: string | undefined;
  riskDashboardUrl: string | undefined;
}

// ============================================================================
// Account and Vault Types
// ============================================================================

export interface AccountState {
  address: Address;
  controllerAddress: Address;
  owner: Address;
  subAccountId: number;
  currentHealthScore: number;
  timeOfNextUpdate: number;
  balance: bigint;
  collateralValue: bigint;
  liabilityValue: bigint;
  lastUpdated: number;
}

export interface VaultInfo {
  address: Address;
  asset: Address;
  assetSymbol: string;
  assetDecimals: number;
  name: string;
  oracle: Address;
  unitOfAccount: Address;
  pythFeedIds: Set<Hex>;
}

export interface AccountLiquidity {
  balance: bigint;
  collateralValue: bigint;
  liabilityValue: bigint;
}

export interface LiquidationCheck {
  maxRepay: bigint;
  seizedCollateralShares: bigint;
}

// ============================================================================
// Liquidation Types
// ============================================================================

export interface SwapQuote {
  amountOut: bigint;
  multicallItems: Hex[];
}

export interface LiquidationParams {
  violator: Address;
  vault: Address;
  borrowedAsset: Address;
  collateralVault: Address;
  collateralAsset: Address;
  maxRepay: bigint;
  seizedCollateralShares: bigint;
  profitReceiver: Address;
}

export interface LiquidationData {
  params: LiquidationParams;
  swapData: Hex[];
  pythUpdateData: Hex | undefined;
  pythUpdateFee: bigint;
  estimatedGas: bigint;
  gasPrice: bigint;
  netProfitEth: bigint;
  seizedCollateralAssets: bigint;
  collateralSymbol: string;
  borrowedSymbol: string;
}

export interface LiquidationResult {
  isProfitable: boolean;
  data?: LiquidationData;
}

export interface LiquidationReceipt {
  transactionHash: Hash;
  blockNumber: bigint;
  gasUsed: bigint;
  status: 'success' | 'reverted';
  violator: Address;
  vault: Address;
  collateralVault: Address;
  repaidAmount: bigint;
  seizedAmount: bigint;
}

// ============================================================================
// Event Types
// ============================================================================

export interface AccountStatusCheckEvent {
  account: Address;
  controller: Address;
  blockNumber: bigint;
  transactionHash: Hash;
}

// ============================================================================
// State Persistence Types
// ============================================================================

export interface SerializedAccountState {
  address: string;
  controllerAddress: string;
  owner: string;
  subAccountId: number;
  currentHealthScore: number;
  timeOfNextUpdate: number;
  balance: string;
  collateralValue: string;
  liabilityValue: string;
  lastUpdated: number;
}

export interface SavedState {
  chainId: number;
  lastSavedAt: number;
  lastScannedBlock: string;
  accounts: SerializedAccountState[];
  vaultAddresses: string[];
}

// ============================================================================
// API Response Types
// ============================================================================

export interface PositionResponse {
  address: string;
  owner: string;
  subaccount: number;
  healthScore: number;
  valueBorrowed: string;
  vaultName: string;
  vaultAddress: string;
}

export interface AllPositionsResponse {
  chainId: number;
  positions: PositionResponse[];
  timestamp: number;
}

// ============================================================================
// Priority Queue Types
// ============================================================================

export interface QueueItem {
  address: Address;
  controllerAddress: Address;
  priority: number; // Unix timestamp for next update
}

// ============================================================================
// Health Score Categories
// ============================================================================

export type HealthCategory = 'liquidation' | 'high_risk' | 'low_risk' | 'safe';

export type PositionSize = 'teeny' | 'mini' | 'small' | 'medium' | 'large';

// ============================================================================
// Notification Types
// ============================================================================

export interface SlackNotification {
  type: 'low_health' | 'opportunity' | 'liquidation_executed' | 'error';
  chainId: number;
  account?: Address;
  vault?: Address;
  healthScore?: number;
  profit?: bigint;
  transactionHash?: Hash;
  errorMessage?: string;
}
