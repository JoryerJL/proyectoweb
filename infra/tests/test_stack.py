import json

import pytest
from aws_cdk.assertions import Match, Template

from canaco_infra.app_factory import create_app
from canaco_infra.cloudflare_ips import CLOUDFLARE_IPV4, CLOUDFLARE_IPV6

import aws_cdk as cdk

ACCOUNT = "888577060863"
REGION = "us-east-1"
ENV = cdk.Environment(account=ACCOUNT, region=REGION)
OIDC_ARN = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"


@pytest.fixture(scope="module")
def template() -> Template:
    app = create_app({"budgetEmail": "test@example.com"}, env=ENV)
    stack = app.node.find_child("CanacoProdStack")
    return Template.from_stack(stack)


def _sg_ingress(template: Template) -> list[dict]:
    groups = template.find_resources("AWS::EC2::SecurityGroup")
    assert len(groups) == 1
    return next(iter(groups.values()))["Properties"]["SecurityGroupIngress"]


# --- Network -----------------------------------------------------------------
def test_no_nat_gateway_and_no_endpoints(template):
    template.resource_count_is("AWS::EC2::NatGateway", 0)
    template.resource_count_is("AWS::EC2::VPCEndpoint", 0)


def test_vpc_has_only_public_subnets(template):
    subnets = template.find_resources("AWS::EC2::Subnet")
    assert 1 <= len(subnets) <= 2
    for subnet in subnets.values():
        assert subnet["Properties"]["MapPublicIpOnLaunch"] is True


# --- Security group ----------------------------------------------------------
def test_sg_has_no_ssh(template):
    for rule in _sg_ingress(template):
        assert rule["FromPort"] not in (22,)
        assert rule["ToPort"] not in (22,)


def test_sg_only_80_443_from_cloudflare(template):
    rules = _sg_ingress(template)
    assert {r["FromPort"] for r in rules} == {80, 443}
    v4 = {r["CidrIp"] for r in rules if "CidrIp" in r}
    v6 = {r["CidrIpv6"] for r in rules if "CidrIpv6" in r}
    assert v4 == set(CLOUDFLARE_IPV4)
    assert v6 == set(CLOUDFLARE_IPV6)
    assert len(rules) == 2 * (len(CLOUDFLARE_IPV4) + len(CLOUDFLARE_IPV6))
    assert "0.0.0.0/0" not in v4 and "::/0" not in v6


# --- Instance ----------------------------------------------------------------
def _instance(template: Template) -> dict:
    instances = template.find_resources("AWS::EC2::Instance")
    assert len(instances) == 1
    return next(iter(instances.values()))


def test_instance_hardening(template):
    props = _instance(template)["Properties"]
    assert props["CreditSpecification"] == {"CPUCredits": "standard"}
    assert props["Monitoring"] is False or "Monitoring" not in props
    assert props["PropagateTagsToVolumeOnCreation"] is True


def test_imdsv2_required(template):
    template.has_resource_properties(
        "AWS::EC2::LaunchTemplate",
        {"LaunchTemplateData": Match.object_like({"MetadataOptions": {"HttpTokens": "required"}})},
    )


def test_root_volume_gp3_encrypted(template):
    props = _instance(template)["Properties"]
    ebs = props["BlockDeviceMappings"][0]["Ebs"]
    assert ebs["VolumeType"] == "gp3"
    assert ebs["Encrypted"] is True
    assert ebs["VolumeSize"] == 20
    # The root volume holds Postgres: it must survive instance termination.
    assert ebs["DeleteOnTermination"] is False


def test_ami_is_pinned_literal_not_ssm_parameter(template):
    image_id = _instance(template)["Properties"]["ImageId"]
    assert isinstance(image_id, str), image_id
    params = template.to_json().get("Parameters", {})
    assert not [n for n, v in params.items() if "SSM" in v.get("Type", "") and n != "BootstrapVersion"], "AMI must not be an SSM parameter"


def test_termination_protection_enabled(template):
    assert _instance(template)["Properties"]["DisableApiTermination"] is True


def test_user_data_change_keeps_instance_logical_id(template):
    other = Template.from_stack(
        create_app({"budgetEmail": "test@example.com", "domain": "other.example.org"}, env=ENV).node.find_child(
            "CanacoProdStack"
        )
    )
    other_instance = next(iter(other.find_resources("AWS::EC2::Instance")))
    assert other_instance == next(iter(template.find_resources("AWS::EC2::Instance")))
    assert json.dumps(_instance(template)["Properties"]["UserData"]) != json.dumps(
        next(iter(other.find_resources("AWS::EC2::Instance").values()))["Properties"]["UserData"]
    )


def test_user_data_bootstraps_app(template):
    body = json.dumps(_instance(template)["Properties"]["UserData"])
    for needle in ("fallocate", "cli-plugins", "/opt/canaco", "openssl rand", "env.example"):
        assert needle in body or needle.replace("-", "") in body, needle


def test_user_data_never_builds_on_the_instance(template):
    body = json.dumps(_instance(template)["Properties"]["UserData"])
    assert "--no-build" in body
    assert "compose -f docker-compose.prod.yml pull" in body


def test_instance_role_only_ssm_core(template):
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "ManagedPolicyArns": [
                {
                    "Fn::Join": [
                        "",
                        ["arn:", {"Ref": "AWS::Partition"}, ":iam::aws:policy/AmazonSSMManagedInstanceCore"],
                    ]
                }
            ],
            "AssumeRolePolicyDocument": Match.object_like(
                {"Statement": [Match.object_like({"Principal": {"Service": "ec2.amazonaws.com"}})]}
            ),
        },
    )


def test_elastic_ip_associated(template):
    template.resource_count_is("AWS::EC2::EIP", 1)
    template.resource_count_is("AWS::EC2::EIPAssociation", 1)


# --- Tags --------------------------------------------------------------------
def _tag_map(resource: dict) -> dict:
    return {t["Key"]: t["Value"] for t in resource["Properties"]["Tags"]}


def test_tags_on_instance_and_vpc(template):
    expected = {
        "Project": "canaco",
        "Application": "canaco-web",
        "Environment": "prod",
        "Owner": "joryer",
        "CostCenter": "m4-proyectoweb",
        "ManagedBy": "cdk",
        "Repository": "github.com/JoryerJL/proyectoweb",
    }
    vpc = next(iter(template.find_resources("AWS::EC2::VPC").values()))
    instance = _instance(template)
    for resource in (vpc, instance):
        tags = _tag_map(resource)
        for key, value in expected.items():
            assert tags.get(key) == value, key
    assert _tag_map(instance)["Backup"] == "daily"


# --- Budget ------------------------------------------------------------------
def test_budget_with_tag_filter_and_notifications(template):
    template.has_resource_properties(
        "AWS::Budgets::Budget",
        {
            "Budget": Match.object_like(
                {
                    "BudgetType": "COST",
                    "TimeUnit": "MONTHLY",
                    "BudgetLimit": {"Amount": 15, "Unit": "USD"},
                    "CostFilters": {"TagKeyValue": ["user:Project$canaco"]},
                }
            ),
            "NotificationsWithSubscribers": Match.array_with(
                [
                    {
                        "Notification": Match.object_like(
                            {
                                "NotificationType": "ACTUAL",
                                "ComparisonOperator": "GREATER_THAN",
                                "Threshold": 80,
                                "ThresholdType": "PERCENTAGE",
                            }
                        ),
                        "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "test@example.com"}],
                    },
                    {
                        "Notification": Match.object_like(
                            {
                                "NotificationType": "FORECASTED",
                                "ComparisonOperator": "GREATER_THAN",
                                "Threshold": 100,
                                "ThresholdType": "PERCENTAGE",
                            }
                        ),
                        "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "test@example.com"}],
                    },
                ]
            ),
        },
    )


# --- Backups -----------------------------------------------------------------
def test_dlm_daily_snapshots_retain_7(template):
    template.has_resource_properties(
        "AWS::DLM::LifecyclePolicy",
        {
            "PolicyDetails": Match.object_like(
                {
                    "ResourceTypes": ["VOLUME"],
                    "TargetTags": [{"Key": "Backup", "Value": "daily"}],
                    "Schedules": [
                        Match.object_like(
                            {
                                "RetainRule": {"Count": 7},
                                "CreateRule": Match.object_like({"Interval": 24, "IntervalUnit": "HOURS"}),
                                "CopyTags": True,
                            }
                        )
                    ],
                }
            )
        },
    )


def test_dlm_role_uses_managed_policy(template):
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": Match.object_like(
                {"Statement": [Match.object_like({"Principal": {"Service": "dlm.amazonaws.com"}})]}
            ),
            "ManagedPolicyArns": Match.array_with(
                [
                    {
                        "Fn::Join": [
                            "",
                            [
                                "arn:",
                                {"Ref": "AWS::Partition"},
                                ":iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole",
                            ],
                        ]
                    }
                ]
            ),
        },
    )


# --- Alarm -------------------------------------------------------------------
def test_system_status_alarm_recovers_instance(template):
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "MetricName": "StatusCheckFailed_System",
            "Namespace": "AWS/EC2",
            "AlarmActions": [
                {"Fn::Join": ["", ["arn:", {"Ref": "AWS::Partition"}, f":automate:{REGION}:ec2:recover"]]}
            ],
        },
    )


# --- GitHub OIDC deploy role -------------------------------------------------
def test_deploy_role_trust_is_exact(template):
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": "canaco-github-deploy",
            "AssumeRolePolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Principal": {"Federated": OIDC_ARN},
                        "Condition": {
                            "StringEquals": {
                                "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                "token.actions.githubusercontent.com:sub": (
                                    "repo:JoryerJL/proyectoweb:environment:production"
                                ),
                            }
                        },
                    }
                ],
            },
        },
    )


def test_oidc_provider_is_imported_not_created(template):
    template.resource_count_is("AWS::IAM::OIDCProvider", 0)
    template.resource_count_is("Custom::AWSCDKOpenIdConnectProvider", 0)


def _deploy_statements(template: Template) -> list[dict]:
    policies = template.find_resources("AWS::IAM::Policy")
    for policy in policies.values():
        roles = policy["Properties"]["Roles"]
        if any("Deploy" in json.dumps(r) for r in roles):
            return policy["Properties"]["PolicyDocument"]["Statement"]
    raise AssertionError("deploy policy not found")


def test_deploy_policy_is_least_privilege(template):
    statements = _deploy_statements(template)
    send = [s for s in statements if "ssm:SendCommand" in _as_list(s["Action"])]
    assert len(send) == 2
    for s in send:
        assert s["Resource"] != "*"
    tagged = [s for s in send if "Condition" in s]
    assert len(tagged) == 1
    assert tagged[0]["Condition"] == {"StringEquals": {"ssm:resourceTag/Project": "canaco"}}
    doc = [s for s in send if "Condition" not in s][0]
    assert "document/AWS-RunShellScript" in json.dumps(doc["Resource"])
    # Only the read-only actions AWS requires to be account-wide use "*".
    wildcard = [s for s in statements if s["Resource"] == "*"]
    actions = {a for s in wildcard for a in _as_list(s["Action"])}
    assert actions == {"ssm:GetCommandInvocation", "ssm:ListCommandInvocations", "ec2:DescribeInstances"}


def _as_list(value):
    return value if isinstance(value, list) else [value]


# --- Outputs -----------------------------------------------------------------
def test_outputs(template):
    outputs = template.to_json()["Outputs"]
    assert {"ElasticIp", "InstanceId", "DeployRoleArn", "SsmSessionCommand"} <= set(outputs)


# --- Inputs ------------------------------------------------------------------
def test_synth_fails_without_budget_email():
    with pytest.raises(ValueError, match="budgetEmail"):
        create_app({})


def test_offline_synth_uses_account_from_context(monkeypatch):
    # CI has no AWS credentials: account/region come from context so the
    # committed cdk.context.json (pinned AMI) can be used without lookups.
    monkeypatch.delenv("CDK_DEFAULT_ACCOUNT", raising=False)
    monkeypatch.delenv("CDK_DEFAULT_REGION", raising=False)
    app = create_app({"budgetEmail": "ci@example.com", "account": ACCOUNT})
    stack = app.node.find_child("CanacoProdStack")
    assert stack.account == ACCOUNT
    assert stack.region == REGION
