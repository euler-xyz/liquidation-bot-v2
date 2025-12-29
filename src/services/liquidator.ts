import type { Address, Hex, Hash } from 'viem';
import { encodeFunctionData } from 'viem';
import type {
  LiquidationResult,
  LiquidationData,
  LiquidationParams,
  LiquidationReceipt,
} from '../core/types';
import { getConfig, getChainConfig } from '../core/config';
import { type Account } from '../core/account';
import { type Vault, getVault } from '../core/vault';
import {
  getCollaterals,
  getLiquidatorContract,
  getAssetInfo,
  LIQUIDATOR_ABI,
} from '../blockchain/contracts';
import {
  getPublicClient,
  getWalletClient,
  getLiquidatorAddress,
  getGasPrice,
} from '../blockchain/client';
import { getQuoter } from './quoter';
import { getOracleHandler } from './oracle-handler';
import { getNotifier } from './notifier';
import { GAS_PRICE_BUFFER, SWAP_AMOUNT_MULTIPLIER } from '../utils/constants';
import { logger } from '../utils/logger';

/**
 * Service for simulating and executing liquidations.
 */
export class Liquidator {
  private chainId: number;

  constructor(chainId: number) {
    this.chainId = chainId;
  }

  /**
   * Simulate liquidation for an account and find the most profitable collateral.
   */
  async simulateLiquidation(account: Account): Promise<LiquidationResult> {
    const config = getConfig();
    const chainConfig = getChainConfig(this.chainId);

    // Get violator's collaterals
    const collaterals = await getCollaterals(this.chainId, account.address);

    if (collaterals.length === 0) {
      logger.debug(
        { chainId: this.chainId, account: account.address },
        'No collaterals found for account'
      );
      return { isProfitable: false };
    }

    let bestLiquidation: LiquidationData | null = null;

    // Check each collateral for profitability
    for (const collateralVaultAddress of collaterals) {
      try {
        const liquidationData = await this.calculateLiquidationProfit(
          account,
          collateralVaultAddress
        );

        if (liquidationData && liquidationData.netProfitEth > 0n) {
          if (!bestLiquidation || liquidationData.netProfitEth > bestLiquidation.netProfitEth) {
            bestLiquidation = liquidationData;
          }
        }
      } catch (error) {
        logger.debug(
          {
            chainId: this.chainId,
            account: account.address,
            collateralVault: collateralVaultAddress,
            error,
          },
          'Failed to calculate liquidation profit for collateral'
        );
      }
    }

    if (bestLiquidation) {
      logger.info(
        {
          chainId: this.chainId,
          account: account.address,
          collateralVault: bestLiquidation.params.collateralVault,
          profit: bestLiquidation.netProfitEth.toString(),
        },
        'Profitable liquidation found'
      );
      return { isProfitable: true, data: bestLiquidation };
    }

    return { isProfitable: false };
  }

  /**
   * Calculate liquidation profit for a specific collateral.
   */
  private async calculateLiquidationProfit(
    account: Account,
    collateralVaultAddress: Address
  ): Promise<LiquidationData | null> {
    const config = getConfig();
    const chainConfig = getChainConfig(this.chainId);
    const vault = account.vault;

    // Get liquidation parameters
    const liquidationCheck = await vault.checkLiquidation(
      account.address,
      collateralVaultAddress
    );

    if (liquidationCheck.maxRepay === 0n) {
      return null;
    }

    // Get vault info
    const vaultInfo = await vault.getInfo();
    const collateralVault = getVault(this.chainId, collateralVaultAddress);
    const collateralInfo = await collateralVault.getInfo();

    // Convert seized shares to assets
    const seizedCollateralAssets = await collateralVault.convertToAssets(
      liquidationCheck.seizedCollateralShares
    );

    // Get swap quote for collateral to borrowed asset
    const quoter = getQuoter();
    const swapQuote = await quoter.getLiquidationSwapQuote(
      this.chainId,
      collateralInfo.asset,
      vaultInfo.asset,
      seizedCollateralAssets,
      liquidationCheck.maxRepay,
      vault.address,
      account.address
    );

    // Calculate leftover after repayment
    const leftoverBorrow = swapQuote.amountOut - liquidationCheck.maxRepay;

    if (leftoverBorrow <= 0n) {
      logger.debug(
        {
          chainId: this.chainId,
          account: account.address,
          amountOut: swapQuote.amountOut.toString(),
          maxRepay: liquidationCheck.maxRepay.toString(),
        },
        'Swap quote insufficient for repayment'
      );
      return null;
    }

    // Convert leftover to ETH for profit calculation
    let leftoverInEth = leftoverBorrow;
    if (vaultInfo.asset.toLowerCase() !== chainConfig.contracts.WETH.toLowerCase()) {
      const ethQuote = await quoter.getToEthSwapQuote(
        this.chainId,
        vaultInfo.asset,
        leftoverBorrow
      );
      if (ethQuote) {
        leftoverInEth = ethQuote.amountOut;
      }
    }

    // Build liquidation transaction for gas estimation
    const oracleHandler = getOracleHandler();
    const feedIds = vault.getPythFeedIds();

    let pythUpdateData: Hex | undefined;
    let pythUpdateFee = 0n;

    if (feedIds.size > 0 && oracleHandler.hasPythSupport(this.chainId)) {
      pythUpdateData = await oracleHandler.getPythUpdateData(feedIds);
      pythUpdateFee = await oracleHandler.getPythUpdateFee(this.chainId, pythUpdateData);
    }

    const params: LiquidationParams = {
      violator: account.address,
      vault: vault.address,
      borrowedAsset: vaultInfo.asset,
      collateralVault: collateralVaultAddress,
      collateralAsset: collateralInfo.asset,
      maxRepay: liquidationCheck.maxRepay,
      seizedCollateralShares: liquidationCheck.seizedCollateralShares,
      profitReceiver: config.global.profitReceiver,
    };

    // Estimate gas
    const publicClient = getPublicClient(this.chainId);
    const liquidatorContract = getLiquidatorContract(this.chainId);

    let estimatedGas: bigint;
    try {
      if (pythUpdateData) {
        estimatedGas = await publicClient.estimateGas({
          account: getLiquidatorAddress(),
          to: chainConfig.contracts.LIQUIDATOR_CONTRACT,
          data: encodeFunctionData({
            abi: LIQUIDATOR_ABI,
            functionName: 'liquidateSingleCollateralWithPythOracle',
            args: [
              [
                params.violator,
                params.vault,
                params.borrowedAsset,
                params.collateralVault,
                params.collateralAsset,
                params.maxRepay,
                params.seizedCollateralShares,
                params.profitReceiver,
              ],
              swapQuote.multicallItems,
              [pythUpdateData],
            ],
          }),
          value: pythUpdateFee,
        });
      } else {
        estimatedGas = await publicClient.estimateGas({
          account: getLiquidatorAddress(),
          to: chainConfig.contracts.LIQUIDATOR_CONTRACT,
          data: encodeFunctionData({
            abi: LIQUIDATOR_ABI,
            functionName: 'liquidateSingleCollateral',
            args: [
              [
                params.violator,
                params.vault,
                params.borrowedAsset,
                params.collateralVault,
                params.collateralAsset,
                params.maxRepay,
                params.seizedCollateralShares,
                params.profitReceiver,
              ],
              swapQuote.multicallItems,
            ],
          }),
        });
      }
    } catch (error) {
      logger.debug(
        {
          chainId: this.chainId,
          account: account.address,
          error,
        },
        'Gas estimation failed'
      );
      return null;
    }

    // Calculate gas cost
    const gasPrice = await getGasPrice(this.chainId);
    const bufferedGasPrice = BigInt(Math.floor(Number(gasPrice) * GAS_PRICE_BUFFER));
    const gasCost = estimatedGas * bufferedGasPrice;

    // Calculate net profit
    const netProfitEth = leftoverInEth - gasCost;

    return {
      params,
      swapData: swapQuote.multicallItems,
      pythUpdateData,
      pythUpdateFee,
      estimatedGas,
      gasPrice: bufferedGasPrice,
      netProfitEth,
      seizedCollateralAssets,
      collateralSymbol: collateralInfo.assetSymbol,
      borrowedSymbol: vaultInfo.assetSymbol,
    };
  }

  /**
   * Execute a liquidation transaction.
   */
  async executeLiquidation(data: LiquidationData): Promise<LiquidationReceipt> {
    const config = getConfig();
    const chainConfig = getChainConfig(this.chainId);
    const publicClient = getPublicClient(this.chainId);
    const walletClient = getWalletClient(this.chainId);

    logger.info(
      {
        chainId: this.chainId,
        violator: data.params.violator,
        vault: data.params.vault,
        collateralVault: data.params.collateralVault,
        estimatedProfit: data.netProfitEth.toString(),
      },
      'Executing liquidation'
    );

    let hash: Hash;

    try {
      if (data.pythUpdateData && data.pythUpdateFee !== undefined) {
        hash = await walletClient.writeContract({
          chain: null,
          account: null,
          address: chainConfig.contracts.LIQUIDATOR_CONTRACT,
          abi: LIQUIDATOR_ABI,
          functionName: 'liquidateSingleCollateralWithPythOracle',
          args: [
            [
              data.params.violator,
              data.params.vault,
              data.params.borrowedAsset,
              data.params.collateralVault,
              data.params.collateralAsset,
              data.params.maxRepay,
              data.params.seizedCollateralShares,
              data.params.profitReceiver,
            ],
            data.swapData,
            [data.pythUpdateData],
          ],
          value: data.pythUpdateFee,
          gas: data.estimatedGas * 120n / 100n, // 20% buffer
          gasPrice: data.gasPrice,
        });
      } else {
        hash = await walletClient.writeContract({
          chain: null,
          account: null,
          address: chainConfig.contracts.LIQUIDATOR_CONTRACT,
          abi: LIQUIDATOR_ABI,
          functionName: 'liquidateSingleCollateral',
          args: [
            [
              data.params.violator,
              data.params.vault,
              data.params.borrowedAsset,
              data.params.collateralVault,
              data.params.collateralAsset,
              data.params.maxRepay,
              data.params.seizedCollateralShares,
              data.params.profitReceiver,
            ],
            data.swapData,
          ],
          gas: data.estimatedGas * 120n / 100n,
          gasPrice: data.gasPrice,
        });
      }
    } catch (error) {
      logger.error(
        {
          chainId: this.chainId,
          violator: data.params.violator,
          error,
        },
        'Failed to submit liquidation transaction'
      );
      throw error;
    }

    logger.info(
      { chainId: this.chainId, hash },
      'Liquidation transaction submitted'
    );

    // Wait for receipt
    const receipt = await publicClient.waitForTransactionReceipt({
      hash,
      timeout: 120_000, // 2 minutes
    });

    const result: LiquidationReceipt = {
      transactionHash: hash,
      blockNumber: receipt.blockNumber,
      gasUsed: receipt.gasUsed,
      status: receipt.status === 'success' ? 'success' : 'reverted',
      violator: data.params.violator,
      vault: data.params.vault,
      collateralVault: data.params.collateralVault,
      repaidAmount: data.params.maxRepay,
      seizedAmount: data.seizedCollateralAssets,
    };

    if (result.status === 'success') {
      logger.info(
        {
          chainId: this.chainId,
          hash,
          gasUsed: receipt.gasUsed.toString(),
          violator: data.params.violator,
        },
        'Liquidation executed successfully'
      );

      // Notify
      const notifier = getNotifier();
      await notifier.notifyLiquidationExecuted(
        this.chainId,
        data.params.violator,
        hash,
        data.collateralSymbol,
        data.borrowedSymbol,
        data.params.maxRepay,
        data.seizedCollateralAssets,
        Number(data.netProfitEth) / 1e18
      );
    } else {
      logger.error(
        {
          chainId: this.chainId,
          hash,
          violator: data.params.violator,
        },
        'Liquidation transaction reverted'
      );
    }

    return result;
  }
}

// Liquidator cache per chain
const liquidatorCache = new Map<number, Liquidator>();

export function getLiquidator(chainId: number): Liquidator {
  let liquidator = liquidatorCache.get(chainId);
  if (!liquidator) {
    liquidator = new Liquidator(chainId);
    liquidatorCache.set(chainId, liquidator);
  }
  return liquidator;
}
