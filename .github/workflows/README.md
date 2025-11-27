# GitHub Actions Workflows

## Deploy Workflow

The `deploy.yml` workflow automatically deploys the liquidation bot to AWS ECS using CDK when code is pushed to the `main` branch.

### Required GitHub Secrets

Configure the following secrets in your GitHub repository settings (Settings → Secrets and variables → Actions):

**Required:**
1. **AWS_ACCESS_KEY_ID** - AWS access key with permissions to deploy CDK stacks
2. **AWS_SECRET_ACCESS_KEY** - AWS secret access key
3. **AWS_ACCOUNT_ID** - AWS account ID
4. **SECRET_NAME** - Name of the AWS Secrets Manager secret (e.g., `mewler-liquidation-bot/config`)
   - The secret must contain `LIQUIDATOR_EOA` and `LIQUIDATOR_PRIVATE_KEY`

**Optional (recommended for security):**
5. **SECRET_NAME** - Name of the AWS Secrets Manager secret (e.g., `mewler-liquidation-bot/config`)
6. **GLUEX_API_KEY** - Gluex API key (overrides hardcoded value in app.py)
7. **GLUEX_UNIQUE_PID** - Gluex unique PID (overrides hardcoded value in app.py)
8. **MAINNET_RPC_URL** - Mainnet RPC URL (overrides hardcoded value in app.py)
9. **BASE_RPC_URL** - Base chain RPC URL (overrides hardcoded value in app.py)
10. **ARBITRUM_RPC_URL** - Arbitrum RPC URL (overrides hardcoded value in app.py)
11. **SLACK_WEBHOOK_URL** - Slack webhook URL (overrides hardcoded value in app.py)

**Note:** It's recommended to move sensitive values (API keys, RPC URLs with keys) from `cdk/app.py` to GitHub secrets for better security.

### IAM Permissions Required

The AWS credentials need the following permissions:
- CloudFormation (create/update/delete stacks)
- ECS (create/update services, task definitions)
- EC2 (describe VPCs, subnets, security groups)
- IAM (create roles and policies)
- ECR (push/pull container images)
- CloudWatch Logs (create log groups)
- Secrets Manager (read secrets, if using)

### Workflow Steps

1. Checks out the code
2. Sets up Python and Node.js
3. Installs CDK CLI
4. Configures AWS credentials
5. Sets up Python virtual environment and installs CDK dependencies
6. Bootstraps CDK (if needed)
7. Validates the CDK stack with `cdk synth`
8. Deploys the stack with `cdk deploy`

### Manual Trigger

The workflow can also be manually triggered from the Actions tab in GitHub.

