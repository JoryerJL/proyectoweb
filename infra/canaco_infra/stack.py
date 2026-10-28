"""Production stack: one EC2 behind Cloudflare, deployed via GitHub OIDC + SSM."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_dlm as dlm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from constructs import Construct

from .cloudflare_ips import CLOUDFLARE_IPV4, CLOUDFLARE_IPV6
from .user_data import render_user_data

GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"
GITHUB_ENVIRONMENT = "production"
HTTP_PORTS = (80, 443)


class CanacoProdStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        instance_type: str,
        domain: str,
        repo_url: str,
        github_sub_prefix: str,
        monthly_budget_usd: float,
        budget_email: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Network: public subnets only, no NAT, no interface endpoints ---
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
        )

        sg = ec2.SecurityGroup(
            self,
            "WebSg",
            vpc=vpc,
            description="HTTP/HTTPS from Cloudflare only. No SSH (use SSM).",
            allow_all_outbound=True,
        )
        for port in HTTP_PORTS:
            for cidr in CLOUDFLARE_IPV4:
                sg.add_ingress_rule(ec2.Peer.ipv4(cidr), ec2.Port.tcp(port), "Cloudflare")
            for cidr in CLOUDFLARE_IPV6:
                sg.add_ingress_rule(ec2.Peer.ipv6(cidr), ec2.Port.tcp(port), "Cloudflare")

        # --- Instance -------------------------------------------------------
        role = iam.Role(
            self,
            "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
            ],
        )

        user_data = ec2.UserData.custom(render_user_data(domain, repo_url))

        instance = ec2.Instance(
            self,
            "Instance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType(instance_type),
            # Pinned through the context cache (cdk.context.json): a new AL2023
            # release must NOT silently replace the instance. To upgrade on
            # purpose: `cdk context --reset <key>` (see docs), then deploy.
            machine_image=ec2.MachineImage.latest_amazon_linux2023(
                cpu_type=ec2.AmazonLinuxCpuType.X86_64,
                cached_in_context=True,
            ),
            security_group=sg,
            role=role,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        20,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                        # Postgres lives here: keep the volume even if the instance goes away.
                        delete_on_termination=False,
                    ),
                )
            ],
            require_imdsv2=True,
            disable_api_termination=True,
            detailed_monitoring=False,
            # STANDARD avoids surprise "unlimited" burst charges on t3.
            credit_specification=ec2.CpuCredits.STANDARD,
            propagate_tags_to_volume_on_creation=True,
            # Editing user data must never replace the instance (it holds the
            # Postgres volume). It only runs at first boot; see docs.
            user_data_causes_replacement=False,
            user_data=user_data,
        )
        cdk.Tags.of(instance).add("Backup", "daily")

        eip = ec2.CfnEIP(self, "Eip", domain="vpc")
        ec2.CfnEIPAssociation(
            self,
            "ElasticIpAssociation",
            allocation_id=eip.attr_allocation_id,
            instance_id=instance.instance_id,
        )

        # --- Self-healing: recover on underlying hardware failure -----------
        alarm = cloudwatch.Alarm(
            self,
            "SystemStatusAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/EC2",
                metric_name="StatusCheckFailed_System",
                dimensions_map={"InstanceId": instance.instance_id},
                statistic="Maximum",
                period=cdk.Duration.minutes(1),
            ),
            threshold=1,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="EC2 system status check failed: auto-recover the instance.",
        )
        alarm.add_alarm_action(cw_actions.Ec2Action(cw_actions.Ec2InstanceAction.RECOVER))

        # --- Backups: daily EBS snapshots, keep 7 ---------------------------
        dlm_role = iam.Role(
            self,
            "DlmRole",
            assumed_by=iam.ServicePrincipal("dlm.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSDataLifecycleManagerServiceRole"
                )
            ],
        )
        dlm.CfnLifecyclePolicy(
            self,
            "DailySnapshots",
            description="Daily EBS snapshots of volumes tagged Backup daily - retain 7",
            state="ENABLED",
            execution_role_arn=dlm_role.role_arn,
            policy_details=dlm.CfnLifecyclePolicy.PolicyDetailsProperty(
                resource_types=["VOLUME"],
                target_tags=[cdk.CfnTag(key="Backup", value="daily")],
                schedules=[
                    dlm.CfnLifecyclePolicy.ScheduleProperty(
                        name="daily",
                        create_rule=dlm.CfnLifecyclePolicy.CreateRuleProperty(
                            interval=24, interval_unit="HOURS", times=["03:00"]
                        ),
                        retain_rule=dlm.CfnLifecyclePolicy.RetainRuleProperty(count=7),
                        copy_tags=True,
                    )
                ],
            ),
        )

        # --- GitHub Actions deploy role (OIDC, no stored credentials) -------
        oidc_arn = f"arn:aws:iam::{self.account}:oidc-provider/{GITHUB_OIDC_HOST}"
        deploy_role = iam.Role(
            self,
            "DeployRole",
            role_name="canaco-github-deploy",
            description="Assumed by GitHub Actions to deploy through SSM Run Command.",
            assumed_by=iam.FederatedPrincipal(
                oidc_arn,
                conditions={
                    "StringEquals": {
                        f"{GITHUB_OIDC_HOST}:aud": "sts.amazonaws.com",
                        f"{GITHUB_OIDC_HOST}:sub": (
                            f"{github_sub_prefix}:environment:{GITHUB_ENVIRONMENT}"
                        ),
                    }
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )
        deploy_role.add_to_policy(
            iam.PolicyStatement(
                sid="RunShellScriptDocument",
                actions=["ssm:SendCommand"],
                resources=[f"arn:aws:ssm:{self.region}::document/AWS-RunShellScript"],
            )
        )
        deploy_role.add_to_policy(
            iam.PolicyStatement(
                sid="SendCommandToTaggedInstances",
                actions=["ssm:SendCommand"],
                resources=[f"arn:aws:ec2:{self.region}:{self.account}:instance/*"],
                conditions={"StringEquals": {"ssm:resourceTag/Project": "canaco"}},
            )
        )
        deploy_role.add_to_policy(
            iam.PolicyStatement(
                # These read-only APIs do not support resource-level permissions.
                sid="ReadOnlyLookups",
                actions=[
                    "ssm:GetCommandInvocation",
                    "ssm:ListCommandInvocations",
                    "ec2:DescribeInstances",
                ],
                resources=["*"],
            )
        )

        # --- Budget: monthly cost of everything tagged Project=canaco -------
        subscribers = [
            budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=budget_email)
        ]
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="canaco-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=monthly_budget_usd, unit="USD"
                ),
                # Requires the "Project" cost allocation tag to be activated.
                cost_filters={"TagKeyValue": ["user:Project$canaco"]},
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=80,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=subscribers,
                ),
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="FORECASTED",
                        comparison_operator="GREATER_THAN",
                        threshold=100,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=subscribers,
                ),
            ],
        )

        # --- Outputs --------------------------------------------------------
        cdk.CfnOutput(self, "ElasticIp", value=eip.ref, description="Point the Cloudflare A record here")
        cdk.CfnOutput(self, "InstanceId", value=instance.instance_id)
        cdk.CfnOutput(self, "DeployRoleArn", value=deploy_role.role_arn,
                      description="Set as the GitHub variable AWS_DEPLOY_ROLE_ARN")
        cdk.CfnOutput(
            self,
            "SsmSessionCommand",
            value=f"aws ssm start-session --target {instance.instance_id} --region {self.region}",
        )
