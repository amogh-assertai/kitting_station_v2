from flask import Blueprint

cv_ingest_bp = Blueprint(
    "cv_ingest",
    __name__,
)

from . import routes  # noqa: E402,F401
