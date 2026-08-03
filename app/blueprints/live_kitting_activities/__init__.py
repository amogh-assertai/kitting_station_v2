from flask import Blueprint

live_kitting_activities_bp = Blueprint(
    "live_kitting_activities",
    __name__,
    template_folder="../../templates/live_kitting_activities",
)

from . import routes  # noqa: E402,F401
