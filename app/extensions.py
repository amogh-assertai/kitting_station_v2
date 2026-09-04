"""
Shared extension singletons.

Flask-SocketIO needs one instance shared between:
  - app/__init__.py (calls socketio.init_app(app))
  - app.py (calls socketio.run(app, ...) instead of app.run(...))
  - any blueprint that needs to emit events (currently: cv_ingest)

Kept in its own module (rather than created inline in create_app() and
returned) so create_app()'s signature doesn't change - nothing that
already calls create_app() and expects a single Flask app back needs to
change. This is the standard Flask-SocketIO app-factory pattern.
"""

from flask_socketio import SocketIO

# async_mode left as "threading" explicitly rather than the default
# eventlet/gevent auto-detection - this app has no eventlet/gevent in
# requirements.txt, and threading mode works with the existing
# `app.run()` -> `socketio.run()` swap with zero other infra changes.
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")
