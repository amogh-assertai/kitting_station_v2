from app import create_app
from app.config.loader import load_settings
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    settings = load_settings()
    # socketio.run() replaces app.run() - required so the same server
    # process handles both normal HTTP routes and the Socket.IO
    # websocket/polling transport used to push live detection updates
    # to the monitor page. async_mode="threading" (set in
    # app/extensions.py) means no eventlet/gevent monkey-patching is
    # needed - this is otherwise a drop-in replacement for app.run().
    socketio.run(
        app,
        host=settings["app"]["host"],
        port=settings["app"]["port"],
        debug=settings["app"]["debug"],
        allow_unsafe_werkzeug=True,
    )
