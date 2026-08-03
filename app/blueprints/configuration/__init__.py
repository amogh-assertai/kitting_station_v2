from flask import Blueprint

configuration_bp = Blueprint(
    "configuration",
    __name__,
    template_folder="../../templates/configuration",
)

from . import routes  # noqa: E402,F401
