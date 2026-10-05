"""Application tracker package (workstream I).

Manages `TrackerStatus` (the user's customizable status pipeline) and
`Application` (one row per job application) on top of `storage.json_store`.
See `tracker/service.py` for the functions and `tracker/routes.py` for the
FastAPI router that exposes them.
"""
