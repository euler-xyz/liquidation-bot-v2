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
# Required: Set SECRET_NAME environment variable to use AWS Secrets Manager
#   The secret must contain LIQUIDATOR_EOA and LIQUIDATOR_PRIVATE_KEY
# Optional: Set container_environment to pass non-sensitive environment variables directly
MewlerLiquidationBotStack(
    app,
    "MewlerLiquidationBotStack",
    env=env,
    vpc_id="vpc-01e44f96507b5ea1b",
    cluster_name="hypurr-liquidator-cluster",
    secret_name=os.getenv("SECRET_NAME", "mewler-liquidation-bot/config"),
    container_environment={
        # Non-sensitive configuration values
        # RPC URLs (can be overridden by secrets)
        "MAINNET_RPC_URL": "https://eth-mainnet.g.alchemy.com/v2/FDD0XfX77DTxUk3qykJ3U",
        "BASE_RPC_URL": "https://eth-mainnet.g.alchemy.com/v2/FDD0XfX77DTxUk3qykJ3U",
        "ARBITRUM_RPC_URL": "https://eth-mainnet.g.alchemy.com/v2/FDD0XfX77DTxUk3qykJ3U",
        # GlueX API Configuration (can be overridden by secrets)
        "GLUEX_API_URL": "https://router.gluex.xyz/v1/quote",
        "GLUEX_UNIQUE_PID": "657a8d5a95d73a70a4b49319544a42ad61d689c83679fcfe6b80e8e9b51cfe2c",
        "GLUEX_API_KEY": "SVQkMIOLo9O2NpA0xI0pQGPV1FYIYXmk",
        ### OPTIONAL ###
        # Slack webhook URL for sending notifications
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/SLACK_KEY",
        # URL for the liquidation UI, if including in the slack notification
        "RISK_DASHBOARD_URL": "http://127.0.0.1:8080",
        # Note: LIQUIDATOR_EOA and LIQUIDATOR_PRIVATE_KEY must be in Secrets Manager
    },
)

app.synth()
