"""
Default tracker statuses, seeded for every new user at signup. Consumed by
the Auth workstream (`app/auth.py`) on user creation to populate that user's
`tracker_statuses.json`. Users can add/remove/rename/recolor/reorder
afterward via `/tracker/statuses` routes -- this list is just the seed.
"""

DEFAULT_STATUSES = [
    {"label": "Need to Apply", "color": "#E0E0E0"},
    {"label": "Applied", "color": "#C8E6C9"},
    {"label": "Unsolicited Application", "color": "#7E57C2"},
    {"label": "Email to be sent", "color": "#2196F3"},
    {"label": "Need Referral", "color": "#E53935"},
    {"label": "First Round scheduled", "color": "#FFAB91"},
    {"label": "Second Round scheduled", "color": "#CFD8DC"},
    {"label": "Interviewed", "color": "#B3E5FC"},
    {"label": "Lost track of round", "color": "#E1BEE7"},
    {"label": "No Reply", "color": "#795548"},
    {"label": "Accepted", "color": "#2E7D32"},
    {"label": "Rejected", "color": "#B71C1C"},
    {"label": "Applied but closed", "color": "#8D2E2E"},
    {"label": "Closed", "color": "#D32F2F"},
]
