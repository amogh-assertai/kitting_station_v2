from flask import render_template

from . import history_bp


@history_bp.route("/history")
def index():
    return render_template("history/index.html", active_page="history")
