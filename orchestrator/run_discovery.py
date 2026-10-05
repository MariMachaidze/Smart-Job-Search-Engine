"""
orchestrator/run_discovery.py -- CLI entrypoint for discovery_graph (plan
section 11 / section 9's "manual override ... invokes the same
discovery_graph on demand").

Usage (from the repo root):
    python -m orchestrator.run_discovery --user-id <id>
    python -m orchestrator.run_discovery --all

`--all` iterates every account in data/users.json (mirrors the shape of
orchestrator/scheduled_jobs.py's run_daily_discovery_for_all_users sketch in
plan section 9, which workstream K owns) and runs discovery for each one in
turn. A single user's run raising unexpectedly (vs. the graph's own
internal per-company/per-job error collection, which never raises) is
logged and does not stop the batch -- same "per-item errors logged, not
fatal" convention used throughout this codebase.
"""
import argparse
import asyncio

from storage import json_store

from orchestrator.discovery_graph import discovery_graph


def _initial_state(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "companies": [],
        "discovered_jobs": [],
        "succeeded_companies": [],
        "persisted_jobs": [],
        "filtered_jobs": [],
        "profile": None,
        "scored_jobs": [],
        "errors": [],
    }


async def run_for_user(user_id: str) -> dict:
    return await discovery_graph.ainvoke(_initial_state(user_id))


def _report(user_id: str, result: dict) -> None:
    companies = result.get("companies") or []
    persisted = result.get("persisted_jobs") or []
    scored = result.get("scored_jobs") or []
    errors = result.get("errors") or []

    print(
        f"user_id={user_id}: {len(companies)} companies, "
        f"{len(persisted)} jobs persisted, {len(scored)} jobs scored this run, "
        f"{len(errors)} errors."
    )
    for err in errors:
        print(f"  ERROR: {err}")


async def run_all() -> None:
    users = json_store.load_users()
    if not users:
        print("No users found in data/users.json -- nothing to do.")
        return

    for user in users:
        user_id = user.get("user_id")
        print(f"\n=== discovery_graph for user_id={user_id} ===")
        try:
            result = await run_for_user(user_id)
        except Exception as exc:  # noqa: BLE001 - one user's run must not abort the batch
            print(f"  FATAL (uncaught) for user_id={user_id}: {exc}")
            continue
        _report(user_id, result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run discovery_graph (job discovery + scoring) for one user or every user."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id", help="Run discovery for this single user_id.")
    group.add_argument(
        "--all", action="store_true", help="Run discovery for every user in data/users.json."
    )
    args = parser.parse_args()

    if args.all:
        asyncio.run(run_all())
    else:
        result = asyncio.run(run_for_user(args.user_id))
        _report(args.user_id, result)


if __name__ == "__main__":
    main()
