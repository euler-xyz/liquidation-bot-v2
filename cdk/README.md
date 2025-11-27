# CDK Deployment for Mewler Liquidation Bot

This directory contains the AWS CDK (Python) scripts to deploy the mewler-liquidation-bot Docker container to AWS ECS Fargate.

## Prerequisites

1. AWS CLI configured with appropriate credentials
2. CDK CLI installed (`npm install -g aws-cdk`)
3. Python 3.8+ installed
4. Access to the existing VPC (`vpc-01e44f96507b5ea1b`) and ECS cluster (`hypurr-liquidator-cluster`)

## Setup

1. Create and activate a virtual environment:
```bash
cd cdk
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Synthesize CloudFormation template (test):
```bash
cd /Users/andreas/projects/hypurrfi/mewler-liquidation-bot
source cdk/.venv/bin/activate
cdk synth --app "python3 cdk/app.py"
```

### Deploy to AWS:
```bash
cd /Users/andreas/projects/hypurrfi/mewler-liquidation-bot
source cdk/.venv/bin/activate
cdk deploy --app "python3 cdk/app.py"
```

### Environment Variables

The application requires several environment variables at runtime. You can provide them in two ways:

#### Option 1: AWS Secrets Manager (Required for sensitive values)

1. Create a secret in AWS Secrets Manager (e.g., `mewler-liquidation-bot/config`)
2. Add the following **required** keys to the secret:
   - `LIQUIDATOR_EOA` - Public address of the liquidator EOA (required)
   - `LIQUIDATOR_PRIVATE_KEY` - Private key for the liquidator EOA (required)
3. Add the following **optional** keys to the secret:
   - `MAINNET_RPC_URL` - Mainnet RPC endpoint
   - `BASE_RPC_URL` - Base chain RPC endpoint (if using Base)
   - `SWELL_RPC_URL` - Swell chain RPC endpoint (if using Swell)
   - `SONIC_RPC_URL` - Sonic chain RPC endpoint (if using Sonic)
   - `BOB_RPC_URL` - BOB chain RPC endpoint (if using BOB)
   - `BERA_RPC_URL` - Berachain RPC endpoint (if using Berachain)
   - `GLUEX_API_KEY` - Gluex API key
   - `GLUEX_UNIQUE_PID` - Gluex unique PID
   - `SLACK_WEBHOOK_URL` - Slack webhook URL (optional)

3. Set the secret name when deploying (required):
```bash
export SECRET_NAME="mewler-liquidation-bot/config"
cdk deploy --app "python3 cdk/app.py"
```

**Note:** `LIQUIDATOR_EOA` and `LIQUIDATOR_PRIVATE_KEY` must be in Secrets Manager. They cannot be provided via environment variables.

#### Option 2: Environment Variables (for non-sensitive values)

Set environment variables before deploying:
```bash
export GLUEX_API_URL="https://api.gluex.com"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/..."
export RISK_DASHBOARD_URL="https://dashboard.example.com"
export LIQUIDATOR_EOA="0x..."
export GIT_REPO_URL="https://github.com/your-org/mewler-liquidation-bot"
export GIT_BRANCH="main"
```

Note: Environment variables take precedence over secrets. If you set both, the environment variable will be used.

#### Option 3: Direct Configuration in app.py

You can also modify `cdk/app.py` to pass environment variables directly in the `container_environment` dictionary.

## Configuration

The stack uses:
- **VPC**: `vpc-01e44f96507b5ea1b` (same as hypurrfi-liquidator)
- **Cluster**: `hypurr-liquidator-cluster` (same as hypurrfi-liquidator)
- **CPU**: 1024 (1 vCPU)
- **Memory**: 2048 MB (2 GB)
- **Port**: 8080

### Required Environment Variables

The application needs these environment variables (from config_loader.py):

**Must be in AWS Secrets Manager (cannot be provided via environment variables):**
- `LIQUIDATOR_EOA` - Public address of the liquidator EOA
- `LIQUIDATOR_PRIVATE_KEY` - Private key for the liquidator EOA

**Can be in Secrets Manager or environment variables:**
- `MAINNET_RPC_URL` - Mainnet RPC endpoint
- `{CHAIN}_RPC_URL` - Chain-specific RPC (e.g., `BASE_RPC_URL`, `SWELL_RPC_URL`, etc.)

### Optional Environment Variables

- `GLUEX_API_URL` - Gluex API endpoint
- `GLUEX_API_KEY` - Gluex API key (use Secrets Manager)
- `GLUEX_UNIQUE_PID` - Gluex unique PID (use Secrets Manager)
- `SLACK_WEBHOOK_URL` - Slack webhook for notifications
- `RISK_DASHBOARD_URL` - Risk dashboard URL

## Files

- `app.py` - CDK app entry point
- `mewler_liquidation_bot_stack.py` - Stack definition with ECS service
- `requirements.txt` - Python dependencies for CDK