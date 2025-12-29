import type { Address, Hex } from 'viem';
import { getConfig, getChainConfig } from '../core/config';
import type { SwapQuote } from '../core/types';
import { getLiquidatorAddress } from '../blockchain/client';
import { withRetry } from '../utils/retry';
import { logger } from '../utils/logger';

type SwapApiParams = Record<string, string>;

interface SwapApiResponse {
  swap: {
    multicallItems: Array<{
      data: Hex;
    }>;
  };
  amountOut: string;
  route?: unknown;
}

/**
 * Service for getting swap quotes from the DEX API.
 */
export class Quoter {
  private apiUrl: string;

  constructor() {
    const config = getConfig();
    this.apiUrl = config.swapApiUrl;
  }

  /**
   * Get a swap quote for exchanging tokens.
   */
  async getSwapQuote(
    chainId: number,
    tokenIn: Address,
    tokenOut: Address,
    amount: bigint,
    minAmountOut: bigint,
    receiver: Address,
    vaultIn: Address,
    accountIn: Address,
    accountOut: Address,
    options: {
      swapperMode?: '0' | '1'; // 0 = exact input, 1 = exact output
      isRepay?: boolean;
      currentDebt?: bigint;
      targetDebt?: bigint;
      skipSweepDepositOut?: boolean;
    } = {}
  ): Promise<SwapQuote> {
    const config = getConfig();
    const apiParams = config.global.apiParameters;

    const params: SwapApiParams = {
      chainId: chainId.toString(),
      tokenIn,
      tokenOut,
      amount: amount.toString(),
      receiver,
      vaultIn,
      origin: getLiquidatorAddress(),
      accountIn,
      accountOut,
      swapperMode: options.swapperMode ?? '0',
      slippage: apiParams.swapSlippage.toString(),
      deadline: (Math.floor(Date.now() / 1000) + apiParams.swapDeadline).toString(),
      isRepay: (options.isRepay ?? false).toString(),
      currentDebt: (options.currentDebt ?? 0n).toString(),
      targetDebt: (options.targetDebt ?? 0n).toString(),
      skipSweepDepositOut: (options.skipSweepDepositOut ?? false).toString(),
    };

    const queryString = new URLSearchParams(params).toString();
    const url = `${this.apiUrl}?${queryString}`;

    logger.debug({ chainId, tokenIn, tokenOut, amount: amount.toString() }, 'Fetching swap quote');

    const response = await withRetry(
      async () => {
        const res = await fetch(url, {
          method: 'GET',
          headers: {
            Accept: 'application/json',
          },
        });

        if (!res.ok) {
          const errorText = await res.text();
          throw new Error(`Swap API error: ${res.status} ${errorText}`);
        }

        return res.json() as Promise<SwapApiResponse>;
      },
      {
        maxRetries: config.global.apiParameters.numRetries,
        baseDelay: config.global.apiParameters.retryDelay * 1000,
        onRetry: (error, attempt) => {
          logger.warn(
            { error: error.message, attempt, chainId },
            'Retrying swap quote request'
          );
        },
      }
    );

    const multicallItems = response.swap.multicallItems.map((item) => item.data);
    const amountOut = BigInt(response.amountOut);

    logger.debug(
      {
        chainId,
        tokenIn,
        tokenOut,
        amountIn: amount.toString(),
        amountOut: amountOut.toString(),
        multicallItems: multicallItems.length,
      },
      'Swap quote received'
    );

    return {
      amountOut,
      multicallItems,
    };
  }

  /**
   * Get a swap quote for liquidation repayment.
   * This swaps seized collateral to the borrowed asset for debt repayment.
   */
  async getLiquidationSwapQuote(
    chainId: number,
    collateralAsset: Address,
    borrowedAsset: Address,
    collateralAmount: bigint,
    maxRepay: bigint,
    borrowedVault: Address,
    violatorAddress: Address
  ): Promise<SwapQuote> {
    const chainConfig = getChainConfig(chainId);
    const config = getConfig();

    // Use 99.9% of collateral for swap to account for rounding
    const swapAmount = (collateralAmount * 999n) / 1000n;

    return this.getSwapQuote(
      chainId,
      collateralAsset,
      borrowedAsset,
      swapAmount,
      maxRepay,
      borrowedVault, // receiver is the vault for repayment
      chainConfig.contracts.SWAPPER, // vaultIn is the swapper
      violatorAddress, // accountIn
      violatorAddress, // accountOut
      {
        isRepay: true,
        currentDebt: maxRepay,
        targetDebt: 0n,
        skipSweepDepositOut: true,
      }
    );
  }

  /**
   * Get a swap quote to convert leftover borrowed asset to ETH.
   * Used for calculating final profit in ETH terms.
   */
  async getToEthSwapQuote(
    chainId: number,
    tokenIn: Address,
    amount: bigint
  ): Promise<SwapQuote | null> {
    const chainConfig = getChainConfig(chainId);
    const wethAddress = chainConfig.contracts.WETH;

    // If already WETH, no swap needed
    if (tokenIn.toLowerCase() === wethAddress.toLowerCase()) {
      return {
        amountOut: amount,
        multicallItems: [],
      };
    }

    try {
      return await this.getSwapQuote(
        chainId,
        tokenIn,
        wethAddress,
        amount,
        0n, // No minimum for quote
        getLiquidatorAddress(),
        chainConfig.contracts.SWAPPER,
        getLiquidatorAddress(),
        getLiquidatorAddress(),
        {
          isRepay: false,
          skipSweepDepositOut: false,
        }
      );
    } catch (error) {
      logger.warn(
        { chainId, tokenIn, amount: amount.toString(), error },
        'Failed to get ETH conversion quote'
      );
      return null;
    }
  }
}

// Singleton instance
let quoterInstance: Quoter | null = null;

export function getQuoter(): Quoter {
  if (!quoterInstance) {
    quoterInstance = new Quoter();
  }
  return quoterInstance;
}
