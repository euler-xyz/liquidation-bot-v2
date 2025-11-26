#!/usr/bin/env python3
"""
CDK App entry point for deploying mewler-liquidation-bot to AWS ECS
"""
import os
import aws_cdk as cdk
from mewler_liquidation_bot_stack import MewlerLiquidationBotStack

app = cdk.App()

# Get environment variables or use defaults
env = cdk.Environment(
    account=os.getenv("CDK_DEPLOY_ACCOUNT"),
    region=os.getenv("CDK_DEPLOY_REGION", "ap-northeast-1"),
)

# Use the same VPC and cluster as hypurrfi-liquidator
# Optional: Set secret_name to use AWS Secrets Manager for sensitive values
# Optional: Set container_environment to pass environment variables directly
MewlerLiquidationBotStack(
    app,
    "MewlerLiquidationBotStack",
    env=env,
    vpc_id="vpc-01e44f96507b5ea1b",
    cluster_name="hypurr-liquidator-cluster",
    secret_name=os.getenv("SECRET_NAME"),  # e.g., "mewler-liquidation-bot/config"
    container_environment={
        # EOA that holds the gas that should be used for liquidation
        "LIQUIDATOR_EOA": "0x651de079c64327612075d9d0ac55762586fe9162",
        "LIQUIDATOR_PRIVATE_KEY": f"{os.getenv('LIQUIDATOR_PRIVATE_KEY')}",
        # RPC URLs
        "MAINNET_RPC_URL": "https://eth-mainnet.g.alchemy.com/v2/FDD0XfX77DTxUk3qykJ3U",
        "BASE_RPC_URL": "https://eth-mainnet.g.alchemy.com/v2/FDD0XfX77DTxUk3qykJ3U",
        "ARBITRUM_RPC_URL": "https://eth-mainnet.g.alchemy.com/v2/FDD0XfX77DTxUk3qykJ3U",
        # GlueX API Configuration
        "GLUEX_API_URL": "https://router.gluex.xyz/v1/quote",
        "GLUEX_UNIQUE_PID": "657a8d5a95d73a70a4b49319544a42ad61d689c83679fcfe6b80e8e9b51cfe2c",
        "GLUEX_API_KEY": "SVQkMIOLo9O2NpA0xI0pQGPV1FYIYXmk",
        ### OPTIONAL ###
        # Slack webhook URL for sending notifications
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/SLACK_KEY",
        # URL for the liquidation UI, if including in the slack notification
        "RISK_DASHBOARD_URL": "http://127.0.0.1:8080",  # Or set them via environment variables before running cdk deploy
    },
)

app.synth()
