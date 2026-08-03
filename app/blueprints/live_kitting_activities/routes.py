from flask import render_template

from . import live_kitting_activities_bp


@live_kitting_activities_bp.route("/live-kitting-activities")
def index():
    return render_template(
        "live_kitting_activities/index.html",
        active_page="live_kitting_activities",
    )
