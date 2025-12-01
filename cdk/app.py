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
)

app.synth()
