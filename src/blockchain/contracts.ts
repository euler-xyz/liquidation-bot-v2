import { getContract, type Address, type GetContractReturnType, type PublicClient } from 'viem';
import { getPublicClient, getMainnetPublicClient } from './client';
import { getChainConfig } from '../core/config';

// Import ABIs
import evaultAbi from './abi/EVault.json';
import evcAbi from './abi/EthereumVaultConnector.json';
import liquidatorAbi from './abi/Liquidator.json';
import oracleAbi from './abi/IOracle.json';
import pythAbi from './abi/IPyth.json';
import erc20Abi from './abi/IERC20.json';
import routerAbi from './abi/EulerRouter.json';

// ============================================================================
// ABI Exports
// ============================================================================

export const EVAULT_ABI = evaultAbi.abi;
export const EVC_ABI = evcAbi.abi;
export const LIQUIDATOR_ABI = liquidatorAbi.abi;
export const ORACLE_ABI = oracleAbi.abi;
export const PYTH_ABI = pythAbi.abi;
export const ERC20_ABI = erc20Abi.abi;
export const ROUTER_ABI = routerAbi.abi;

// ============================================================================
// Contract Types
// ============================================================================

export type EVaultContract = GetContractReturnType<typeof EVAULT_ABI, PublicClient>;
export type EVCContract = GetContractReturnType<typeof EVC_ABI, PublicClient>;
export type LiquidatorContract = GetContractReturnType<typeof LIQUIDATOR_ABI, PublicClient>;
export type OracleContract = GetContractReturnType<typeof ORACLE_ABI, PublicClient>;
export type PythContract = GetContractReturnType<typeof PYTH_ABI, PublicClient>;
export type ERC20Contract = GetContractReturnType<typeof ERC20_ABI, PublicClient>;

// ============================================================================
// Contract Factory Functions
// ============================================================================

export function getEVaultContract(chainId: number, address: Address): EVaultContract {
  const client = getPublicClient(chainId);
  return getContract({
    address,
    abi: EVAULT_ABI,
    client,
  });
}

export function getEVCContract(chainId: number): EVCContract {
  const client = getPublicClient(chainId);
  const chainConfig = getChainConfig(chainId);
  return getContract({
    address: chainConfig.contracts.EVC,
    abi: EVC_ABI,
    client,
  });
}

export function getLiquidatorContract(chainId: number): LiquidatorContract {
  const client = getPublicClient(chainId);
  const chainConfig = getChainConfig(chainId);
  return getContract({
    address: chainConfig.contracts.LIQUIDATOR_CONTRACT,
    abi: LIQUIDATOR_ABI,
    client,
  });
}

export function getOracleContract(chainId: number, address: Address): OracleContract {
  const client = getPublicClient(chainId);
  return getContract({
    address,
    abi: ORACLE_ABI,
    client,
  });
}

export function getPythContract(chainId: number): PythContract | null {
  const chainConfig = getChainConfig(chainId);
  if (!chainConfig.contracts.PYTH || chainConfig.contracts.PYTH === '0x0000000000000000000000000000000000000000') {
    return null;
  }
  const client = getPublicClient(chainId);
  return getContract({
    address: chainConfig.contracts.PYTH,
    abi: PYTH_ABI,
    client,
  });
}

export function getERC20Contract(chainId: number, address: Address): ERC20Contract {
  const client = getPublicClient(chainId);
  return getContract({
    address,
    abi: ERC20_ABI,
    client,
  });
}

// ============================================================================
// Mainnet Oracle Contracts (for cross-chain price lookups)
// ============================================================================

export function getMainnetOracleContract(address: Address): OracleContract {
  const client = getMainnetPublicClient();
  return getContract({
    address,
    abi: ORACLE_ABI,
    client,
  });
}

// ============================================================================
// Contract Method Helpers
// ============================================================================

export async function getAssetInfo(
  chainId: number,
  assetAddress: Address
): Promise<{ symbol: string; decimals: number }> {
  const contract = getERC20Contract(chainId, assetAddress);

  const [symbol, decimals] = await Promise.all([
    contract.read.symbol() as Promise<string>,
    contract.read.decimals() as Promise<number>,
  ]);

  return { symbol, decimals };
}

export async function getVaultAsset(chainId: number, vaultAddress: Address): Promise<Address> {
  const contract = getEVaultContract(chainId, vaultAddress);
  return contract.read.asset() as Promise<Address>;
}

export async function getVaultOracle(chainId: number, vaultAddress: Address): Promise<Address> {
  const contract = getEVaultContract(chainId, vaultAddress);
  return contract.read.oracle() as Promise<Address>;
}

export async function getVaultUnitOfAccount(chainId: number, vaultAddress: Address): Promise<Address> {
  const contract = getEVaultContract(chainId, vaultAddress);
  return contract.read.unitOfAccount() as Promise<Address>;
}

export async function getAccountLiquidity(
  chainId: number,
  vaultAddress: Address,
  accountAddress: Address
): Promise<{ collateralValue: bigint; liabilityValue: bigint }> {
  const contract = getEVaultContract(chainId, vaultAddress);
  const result = await contract.read.accountLiquidity([accountAddress, true]) as [bigint, bigint];
  return {
    collateralValue: result[0],
    liabilityValue: result[1],
  };
}

export async function getAccountBalance(
  chainId: number,
  vaultAddress: Address,
  accountAddress: Address
): Promise<bigint> {
  const contract = getEVaultContract(chainId, vaultAddress);
  return contract.read.balanceOf([accountAddress]) as Promise<bigint>;
}

export async function checkLiquidation(
  chainId: number,
  vaultAddress: Address,
  liquidatorAddress: Address,
  violatorAddress: Address,
  collateralVaultAddress: Address
): Promise<{ maxRepay: bigint; seizedCollateral: bigint }> {
  const contract = getEVaultContract(chainId, vaultAddress);
  const result = await contract.read.checkLiquidation([
    liquidatorAddress,
    violatorAddress,
    collateralVaultAddress,
  ]) as [bigint, bigint];
  return {
    maxRepay: result[0],
    seizedCollateral: result[1],
  };
}

export async function convertToAssets(
  chainId: number,
  vaultAddress: Address,
  shares: bigint
): Promise<bigint> {
  const contract = getEVaultContract(chainId, vaultAddress);
  return contract.read.convertToAssets([shares]) as Promise<bigint>;
}

export async function getLTVList(
  chainId: number,
  vaultAddress: Address
): Promise<Address[]> {
  const contract = getEVaultContract(chainId, vaultAddress);
  return contract.read.LTVList() as Promise<Address[]>;
}

export async function getCollaterals(
  chainId: number,
  accountAddress: Address
): Promise<Address[]> {
  const contract = getEVCContract(chainId);
  return contract.read.getCollaterals([accountAddress]) as Promise<Address[]>;
}

export async function getControllers(
  chainId: number,
  accountAddress: Address
): Promise<Address[]> {
  const contract = getEVCContract(chainId);
  return contract.read.getControllers([accountAddress]) as Promise<Address[]>;
}
