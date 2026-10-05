"""
Statistics routes (workstream M, plan section 13).

  GET /statistics/summary       -> stats.aggregator.compute_summary
  GET /statistics/timeseries    -> stats.aggregator.compute_status_counts
  GET /statistics/skill-gap     -> stats.skill_gap.analyze_rejection_patterns

All three are thin pass-throughs to workstream J's real, already-tested
functions -- this router's only job is JWT auth + resolving user_id, same
pattern as every other router in this system.
"""
from typing import Literal

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from stats.aggregator import compute_status_counts, compute_summary
from stats.skill_gap import analyze_rejection_patterns

router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("/summary")
async def get_summary(current_user: dict = Depends(get_current_user)):
    return compute_summary(current_user["user_id"])


@router.get("/timeseries")
async def get_timeseries(
    granularity: Literal["daily", "monthly"] = "daily",
    current_user: dict = Depends(get_current_user),
):
    return compute_status_counts(current_user["user_id"], granularity)


@router.get("/skill-gap")
async def get_skill_gap(current_user: dict = Depends(get_current_user)):
    """Note: analyze_rejection_patterns never raises for the "not enough
    data yet" case -- it returns {"threshold_met": False, ...} instead, per
    stats/skill_gap.py's own contract -- so this route has nothing extra to
    guard against; the frontend distinguishes "no gap found yet" from "a
    real analysis" via the threshold_met field."""
    return analyze_rejection_patterns(current_user["user_id"])
