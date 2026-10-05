"""
orchestrator/ -- LangGraph orchestration (workstream F, plan section 11).

Owns the two batch/on-demand graphs that stitch together the pieces other
workstreams built:

  - discovery_graph.py: load_companies -> discover_jobs -> persist_jobs
    (new/seen/closed diff + geocoding) -> apply_hard_filters -> load_profile
    -> [conditional: has profile?] -> score_jobs -> END

  - tailoring_graph.py: load_job -> load_profile -> fan out to
    tailor_resume + generate_cover_letter (real concurrent branches) -> join
    -> END

`chat_graph.py` (plan section 11, graph 3) and the APScheduler service
(plan section 9) are separate workstreams (H and K) and are NOT part of this
package.
"""
