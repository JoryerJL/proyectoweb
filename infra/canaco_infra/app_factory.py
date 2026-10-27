"""Builds the CDK app: reads context, validates it, applies FinOps tags."""

from __future__ import annotations

import os
from typing import Any, Mapping

import aws_cdk as cdk

from .stack import CanacoProdStack

DEFAULTS: dict[str, Any] = {
    "instanceType": "t3.micro",
    "domain": "canaco.jjjl.dev",
    "repoUrl": "https://github.com/JoryerJL/proyectoweb.git",
    "githubRepo": "JoryerJL/proyectoweb",
    "monthlyBudgetUsd": 15,
    "owner": "joryer",
    "costCenter": "m4-proyectoweb",
}


def create_app(
    context: Mapping[str, Any] | None = None,
    env: cdk.Environment | None = None,
) -> cdk.App:
    """Create the app. `context` overrides cdk.json/-c values (used by tests)."""
    app = cdk.App(context=dict(context) if context else None)
    if env is None:
        # Real runs: the CDK CLI exports CDK_DEFAULT_*. Offline runs (CI, no
        # credentials): fall back to `-c account=<id>`; region defaults to us-east-1.
        account = os.environ.get("CDK_DEFAULT_ACCOUNT") or app.node.try_get_context("account")
        region = os.environ.get("CDK_DEFAULT_REGION") or app.node.try_get_context("region") or "us-east-1"
        env = cdk.Environment(account=account, region=region) if account else None

    def get(key: str) -> Any:
        value = app.node.try_get_context(key)
        return DEFAULTS.get(key) if value is None else value

    budget_email = app.node.try_get_context("budgetEmail")
    if not budget_email:
        raise ValueError(
            "Missing required context 'budgetEmail'. "
            "Run: cdk deploy -c budgetEmail=you@example.com"
        )

    CanacoProdStack(
        app,
        "CanacoProdStack",
        env=env,
        instance_type=str(get("instanceType")),
        domain=str(get("domain")),
        repo_url=str(get("repoUrl")),
        github_repo=str(get("githubRepo")),
        monthly_budget_usd=float(get("monthlyBudgetUsd")),
        budget_email=str(budget_email),
    )

    tags = {
        "Project": "canaco",
        "Application": "canaco-web",
        "Environment": "prod",
        "Owner": str(get("owner")),
        "CostCenter": str(get("costCenter")),
        "ManagedBy": "cdk",
        "Repository": "github.com/JoryerJL/proyectoweb",
    }
    for key, value in tags.items():
        cdk.Tags.of(app).add(key, value)
    return app
