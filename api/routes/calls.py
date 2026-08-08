"""Calls dashboard — the read side of ingested conversations.

Every query here filters on the caller's organization at the SQL level rather
than in Python after the fact. That is a tenant-isolation requirement: our
Postgres is the copy that is properly partitioned even while the vendor's
workspace is not, so this layer is where the client boundary is actually
enforced.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from api.db import db_client
from api.db.models import UserModel, WorkflowModel, WorkflowRunModel
from api.services.auth.depends import get_user

router = APIRouter(prefix="/calls")


class CallSummary(BaseModel):
    run_id: int
    conversation_id: Optional[str]
    agent_id: Optional[str]
    agent_name: Optional[str]
    duration_seconds: Optional[int]
    sentiment: Optional[str]
    created_at: Optional[datetime]
    has_recording: bool


class CallDetail(CallSummary):
    transcript: Optional[Any] = None
    extracted_data: dict[str, Any] = {}
    recording_url: Optional[str] = None


class CallsPage(BaseModel):
    calls: list[CallSummary]
    total: int


class UsageSummary(BaseModel):
    total_calls: int
    total_seconds: int
    by_agent: list[dict[str, Any]]


def _require_organization(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )
    return user.selected_organization_id


def _summary(run: WorkflowRunModel, agent_name: str | None) -> CallSummary:
    return CallSummary(
        run_id=run.id,
        conversation_id=run.elevenlabs_conversation_id,
        agent_id=run.elevenlabs_agent_id,
        agent_name=agent_name,
        duration_seconds=run.duration_seconds,
        sentiment=run.sentiment,
        created_at=run.created_at,
        has_recording=bool(run.recording_url),
    )


@router.get("/")
async def list_calls(
    user: UserModel = Depends(get_user),
    limit: int = Query(50, le=200),
    offset: int = 0,
    agent_id: Optional[str] = None,
) -> CallsPage:
    """List this organization's calls, newest first."""
    organization_id = _require_organization(user)

    async with db_client.async_session() as session:
        # Joined to workflows and filtered on organization_id in SQL — never
        # fetched broadly and filtered afterwards.
        conditions = [
            WorkflowModel.organization_id == organization_id,
            WorkflowRunModel.elevenlabs_conversation_id.isnot(None),
        ]
        if agent_id:
            conditions.append(WorkflowRunModel.elevenlabs_agent_id == agent_id)

        total = await session.scalar(
            select(func.count(WorkflowRunModel.id))
            .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
            .where(*conditions)
        )

        result = await session.execute(
            select(WorkflowRunModel, WorkflowModel.name)
            .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
            .where(*conditions)
            .order_by(WorkflowRunModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        return CallsPage(
            calls=[_summary(run, name) for run, name in result.all()],
            total=total or 0,
        )


@router.get("/usage")
async def usage_summary(
    user: UserModel = Depends(get_user),
    since: Optional[datetime] = None,
) -> UsageSummary:
    """Per-period call and duration totals, broken down by agent."""
    organization_id = _require_organization(user)

    async with db_client.async_session() as session:
        conditions = [
            WorkflowModel.organization_id == organization_id,
            WorkflowRunModel.elevenlabs_conversation_id.isnot(None),
        ]
        if since:
            conditions.append(WorkflowRunModel.created_at >= since)

        result = await session.execute(
            select(
                WorkflowModel.name,
                func.count(WorkflowRunModel.id),
                func.coalesce(func.sum(WorkflowRunModel.duration_seconds), 0),
            )
            .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
            .where(*conditions)
            .group_by(WorkflowModel.name)
            .order_by(func.count(WorkflowRunModel.id).desc())
        )
        rows = result.all()

    return UsageSummary(
        total_calls=sum(r[1] for r in rows),
        total_seconds=sum(int(r[2]) for r in rows),
        by_agent=[
            {"agent_name": r[0], "calls": r[1], "seconds": int(r[2])} for r in rows
        ],
    )


@router.get("/{run_id}")
async def get_call(
    run_id: int,
    user: UserModel = Depends(get_user),
) -> CallDetail:
    """Fetch one call in full.

    The organization filter is part of the lookup, not a check afterwards — a
    run belonging to another client is a 404, indistinguishable from one that
    does not exist.
    """
    organization_id = _require_organization(user)

    async with db_client.async_session() as session:
        result = await session.execute(
            select(WorkflowRunModel, WorkflowModel.name)
            .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
            .where(
                WorkflowRunModel.id == run_id,
                WorkflowModel.organization_id == organization_id,
            )
        )
        row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Call not found")

    run, agent_name = row
    base = _summary(run, agent_name)

    return CallDetail(
        **base.model_dump(),
        transcript=run.transcript,
        extracted_data=run.gathered_context or {},
        recording_url=run.recording_url,
    )
