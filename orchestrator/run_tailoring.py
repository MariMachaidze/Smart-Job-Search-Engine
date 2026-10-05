"""
orchestrator/run_tailoring.py -- CLI entrypoint for tailoring_graph (plan
section 11).

Usage (from the repo root):
    python -m orchestrator.run_tailoring --user-id <id> --job-id <id>
"""
import argparse
import asyncio

from orchestrator.tailoring_graph import tailoring_graph


def _initial_state(user_id: str, job_id: str) -> dict:
    return {
        "user_id": user_id,
        "job_id": job_id,
        "job": None,
        "profile": None,
        "resume_doc": None,
        "cover_letter_doc": None,
        "errors": [],
    }


async def run_for_job(user_id: str, job_id: str) -> dict:
    return await tailoring_graph.ainvoke(_initial_state(user_id, job_id))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run tailoring_graph (tailored resume + cover letter) for one job_id."
    )
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    result = asyncio.run(run_for_job(args.user_id, args.job_id))

    resume_doc = result.get("resume_doc")
    cover_letter_doc = result.get("cover_letter_doc")

    print(f"Resume document: {resume_doc.get('display_name') if resume_doc else 'NOT GENERATED'}")
    print(
        f"Cover letter document: "
        f"{cover_letter_doc.get('display_name') if cover_letter_doc else 'NOT GENERATED'}"
    )

    for err in result.get("errors") or []:
        print(f"ERROR: {err}")


if __name__ == "__main__":
    main()
