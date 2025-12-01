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

        vpc = ec2.Vpc.from_lookup(
            self,
            "ImportedVPC",
            vpc_id=vpc_id,
        )

        cluster = ecs.Cluster.from_cluster_attributes(
            self,
            "ImportedCluster",
            cluster_name=cluster_name,
            vpc=vpc,
            security_groups=[],
        )

        secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "AppSecret",
            secret_name=secret_name,
        )

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

        task_role = iam.Role(
            self,
            "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

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

        task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDefinition",
            family="mewler-liquidation-bot",
            cpu=2048,  # 2 vCPU
            memory_limit_mib=4096,  # 4 GB
            execution_role=task_execution_role,
            task_role=task_role,
        )

        # AWK: For AWS we can provide a different Dockerfile that doesn't need to checkout the repo.
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        image = ecs.ContainerImage.from_asset(
            project_root,
            file="Dockerfile.aws",
        )

        env_vars = container_environment.copy() if container_environment else {}


        doppler_token = ecs.Secret.from_secrets_manager(secret, "DOPPLER_TOKEN")

        container = task_definition.add_container(
            "mewler-liquidation-bot",
            image=image,
            memory_limit_mib=2048,
            environment=env_vars if env_vars else None,
            secrets={
                "DOPPLER_TOKEN": doppler_token,
            },
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="mewler-liquidation-bot",
                log_retention=logs.RetentionDays.THREE_DAYS,
            ),
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()\" || exit 1",
                ],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60),  # Allow time for app to start
            ),
        )

        container.add_port_mappings(
            ecs.PortMapping(
                container_port=8080,
                protocol=ecs.Protocol.TCP,
            )
        )

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
