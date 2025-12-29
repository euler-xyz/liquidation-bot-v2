import type { Address, Hash } from 'viem';
import { getConfig, getChainConfig } from '../core/config';
import { logger } from '../utils/logger';
import { withRetry } from '../utils/retry';

interface SlackMessage {
  text: string;
  blocks?: SlackBlock[];
}

interface SlackBlock {
  type: string;
  text?: {
    type: string;
    text: string;
  };
  fields?: Array<{
    type: string;
    text: string;
  }>;
}

/**
 * Service for sending Slack notifications about liquidation events.
 */
export class Notifier {
  private webhookUrl: string | undefined;
  private riskDashboardUrl: string | undefined;
  private lastErrorAt: Map<string, number> = new Map();

  constructor() {
    const config = getConfig();
    this.webhookUrl = config.slackWebhookUrl;
    this.riskDashboardUrl = config.riskDashboardUrl;
  }

  /**
   * Check if notifications are enabled.
   */
  isEnabled(): boolean {
    return !!this.webhookUrl;
  }

  /**
   * Send a low health account notification.
   */
  async notifyLowHealth(
    chainId: number,
    accountAddress: Address,
    vaultAddress: Address,
    vaultName: string,
    healthScore: number,
    liabilityValueUsd: number
  ): Promise<void> {
    if (!this.isEnabled()) return;

    const chainConfig = getChainConfig(chainId);
    const explorerUrl = chainConfig.explorerUrl;

    const blocks: SlackBlock[] = [
      {
        type: 'header',
        text: {
          type: 'plain_text',
          text: `Low Health Account on ${chainConfig.name}`,
        },
      },
      {
        type: 'section',
        fields: [
          {
            type: 'mrkdwn',
            text: `*Account:*\n<${explorerUrl}/address/${accountAddress}|${this.truncateAddress(accountAddress)}>`,
          },
          {
            type: 'mrkdwn',
            text: `*Vault:*\n${vaultName}`,
          },
          {
            type: 'mrkdwn',
            text: `*Health Score:*\n${healthScore.toFixed(4)}`,
          },
          {
            type: 'mrkdwn',
            text: `*Liability:*\n$${liabilityValueUsd.toLocaleString()}`,
          },
        ],
      },
    ];

    if (this.riskDashboardUrl) {
      blocks.push({
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `<${this.riskDashboardUrl}?chainId=${chainId}&account=${accountAddress}|View in Dashboard>`,
        },
      });
    }

    await this.sendMessage({
      text: `Low health account detected on ${chainConfig.name}`,
      blocks,
    });
  }

  /**
   * Send a liquidation opportunity notification.
   */
  async notifyOpportunity(
    chainId: number,
    accountAddress: Address,
    vaultName: string,
    collateralSymbol: string,
    borrowedSymbol: string,
    profitEth: number
  ): Promise<void> {
    if (!this.isEnabled()) return;

    const chainConfig = getChainConfig(chainId);

    const blocks: SlackBlock[] = [
      {
        type: 'header',
        text: {
          type: 'plain_text',
          text: `Liquidation Opportunity on ${chainConfig.name}`,
        },
      },
      {
        type: 'section',
        fields: [
          {
            type: 'mrkdwn',
            text: `*Account:*\n${this.truncateAddress(accountAddress)}`,
          },
          {
            type: 'mrkdwn',
            text: `*Vault:*\n${vaultName}`,
          },
          {
            type: 'mrkdwn',
            text: `*Collateral:*\n${collateralSymbol}`,
          },
          {
            type: 'mrkdwn',
            text: `*Borrowed:*\n${borrowedSymbol}`,
          },
          {
            type: 'mrkdwn',
            text: `*Est. Profit:*\n${profitEth.toFixed(6)} ETH`,
          },
        ],
      },
    ];

    await this.sendMessage({
      text: `Liquidation opportunity found on ${chainConfig.name}`,
      blocks,
    });
  }

  /**
   * Send a successful liquidation notification.
   */
  async notifyLiquidationExecuted(
    chainId: number,
    accountAddress: Address,
    transactionHash: Hash,
    collateralSymbol: string,
    borrowedSymbol: string,
    repaidAmount: bigint,
    seizedAmount: bigint,
    profitEth: number
  ): Promise<void> {
    if (!this.isEnabled()) return;

    const chainConfig = getChainConfig(chainId);
    const explorerUrl = chainConfig.explorerUrl;

    const blocks: SlackBlock[] = [
      {
        type: 'header',
        text: {
          type: 'plain_text',
          text: `Liquidation Executed on ${chainConfig.name}`,
        },
      },
      {
        type: 'section',
        fields: [
          {
            type: 'mrkdwn',
            text: `*Account:*\n${this.truncateAddress(accountAddress)}`,
          },
          {
            type: 'mrkdwn',
            text: `*Transaction:*\n<${explorerUrl}/tx/${transactionHash}|View>`,
          },
          {
            type: 'mrkdwn',
            text: `*Collateral Seized:*\n${collateralSymbol}`,
          },
          {
            type: 'mrkdwn',
            text: `*Debt Repaid:*\n${borrowedSymbol}`,
          },
          {
            type: 'mrkdwn',
            text: `*Profit:*\n${profitEth.toFixed(6)} ETH`,
          },
        ],
      },
    ];

    await this.sendMessage({
      text: `Liquidation executed successfully on ${chainConfig.name}`,
      blocks,
    });
  }

  /**
   * Send an error notification (rate-limited).
   */
  async notifyError(
    chainId: number,
    errorType: string,
    errorMessage: string,
    context?: Record<string, unknown>
  ): Promise<void> {
    if (!this.isEnabled()) return;

    // Rate limit error notifications
    const config = getConfig();
    const errorKey = `${chainId}:${errorType}`;
    const lastError = this.lastErrorAt.get(errorKey) ?? 0;
    const now = Date.now();

    if (now - lastError < config.global.reportingParameters.errorCooldown * 1000) {
      return;
    }

    this.lastErrorAt.set(errorKey, now);

    const chainConfig = getChainConfig(chainId);

    const blocks: SlackBlock[] = [
      {
        type: 'header',
        text: {
          type: 'plain_text',
          text: `Error on ${chainConfig.name}`,
        },
      },
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `*Type:* ${errorType}\n*Message:* ${errorMessage}`,
        },
      },
    ];

    if (context) {
      blocks.push({
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `*Context:*\n\`\`\`${JSON.stringify(context, null, 2)}\`\`\``,
        },
      });
    }

    await this.sendMessage({
      text: `Error on ${chainConfig.name}: ${errorType}`,
      blocks,
    });
  }

  /**
   * Send a message to Slack.
   */
  private async sendMessage(message: SlackMessage): Promise<void> {
    if (!this.webhookUrl) return;

    try {
      await withRetry(
        async () => {
          const response = await fetch(this.webhookUrl!, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(message),
          });

          if (!response.ok) {
            throw new Error(`Slack webhook failed: ${response.status} ${response.statusText}`);
          }
        },
        {
          maxRetries: 2,
          baseDelay: 1000,
        }
      );
    } catch (error) {
      logger.error({ error }, 'Failed to send Slack notification');
    }
  }

  /**
   * Truncate an address for display.
   */
  private truncateAddress(address: Address): string {
    return `${address.slice(0, 6)}...${address.slice(-4)}`;
  }
}

// Singleton instance
let notifierInstance: Notifier | null = null;

export function getNotifier(): Notifier {
  if (!notifierInstance) {
    notifierInstance = new Notifier();
  }
  return notifierInstance;
}
