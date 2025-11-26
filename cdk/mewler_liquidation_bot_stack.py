"""
CDK Stack for deploying mewler-liquidation-bot to ECS Fargate
"""
import os
from typing import Dict, Optional
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
    Duration,
)
from constructs import Construct


class MewlerLiquidationBotStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc_id: str,
        cluster_name: str,
        secret_name: Optional[str] = None,
        container_environment: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Import existing VPC
        vpc = ec2.Vpc.from_lookup(
            self,
            "ImportedVPC",
            vpc_id=vpc_id,
        )

        # Import existing ECS cluster
        cluster = ecs.Cluster.from_cluster_attributes(
            self,
            "ImportedCluster",
            cluster_name=cluster_name,
            vpc=vpc,
            security_groups=[],
        )

        # Import or create secret if secret_name is provided
        secret = None
        if secret_name:
            secret = secretsmanager.Secret.from_secret_name_v2(
                self,
                "AppSecret",
                secret_name=secret_name,
            )

        # Create task execution role
        task_execution_role = iam.Role(
            self,
            "TaskExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                ),
            ],
        )

        # Create task role
        task_role = iam.Role(
            self,
            "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        # Add permissions to access secrets if secret is provided
        if secret:
            task_execution_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[secret.secret_arn],
                )
            )
            task_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[secret.secret_arn],
                )
            )

        # Create task definition
        task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDefinition",
            family="mewler-liquidation-bot",
            cpu=1024,  # 1 vCPU
            memory_limit_mib=2048,  # 2 GB
            execution_role=task_execution_role,
            task_role=task_role,
        )

        # Build Docker image from Dockerfile
        # Get the project root directory (parent of cdk directory)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        image = ecs.ContainerImage.from_asset(
            project_root,
            file="Dockerfile",
            build_args={
                "GIT_REPO_URL": os.getenv("GIT_REPO_URL", ""),
                "GIT_BRANCH": os.getenv("GIT_BRANCH", "main"),
            },
        )

        # Prepare environment variables
        # Start with any provided container_environment
        env_vars = container_environment.copy() if container_environment else {}
        
        # Add environment variables from os.getenv for non-sensitive values
        # These can be set at CDK deploy time
        optional_env_vars = [
            "GLUEX_API_URL",
            "SLACK_WEBHOOK_URL",
            "RISK_DASHBOARD_URL",
            "LIQUIDATOR_EOA",
        ]
        for env_var in optional_env_vars:
            value = os.getenv(env_var)
            if value:
                env_vars[env_var] = value

        # Prepare secrets mapping
        secrets = {}
        if secret:
            # Map common secret keys that might be in Secrets Manager
            # Users can customize these based on their secret structure
            secret_keys = [
                "LIQUIDATOR_EOA_PRIVATE_KEY",
                "MAINNET_RPC_URL",
                "BASE_RPC_URL",
                "SWELL_RPC_URL",
                "SONIC_RPC_URL",
                "BOB_RPC_URL",
                "BERA_RPC_URL",
                "GLUEX_API_KEY",
                "GLUEX_UNIQUE_PID",
                "SLACK_WEBHOOK_URL",  # Can be in secrets or env
            ]
            
            for key in secret_keys:
                # Only add if not already in env_vars (env vars take precedence)
                if key not in env_vars:
                    secrets[key] = ecs.Secret.from_secrets_manager(secret, key)

        # Add container to task definition
        container = task_definition.add_container(
            "mewler-liquidation-bot",
            image=image,
            memory_limit_mib=2048,
            environment=env_vars if env_vars else None,
            secrets=secrets if secrets else None,
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="mewler-liquidation-bot",
                log_retention=logs.RetentionDays.THREE_DAYS,
            ),
        )

        # Expose port 8080
        container.add_port_mappings(
            ecs.PortMapping(
                container_port=8080,
                protocol=ecs.Protocol.TCP,
            )
        )

        # Create Fargate service
        service = ecs.FargateService(
            self,
            "Service",
            cluster=cluster,
            task_definition=task_definition,
            assign_public_ip=False,
            desired_count=1,
            min_healthy_percent=0,
            max_healthy_percent=200,
        )

        # Add health check (optional, but good practice)
        # Note: ECS will use the container's health check if configured
        # For now, we rely on the /health endpoint in the Flask app

