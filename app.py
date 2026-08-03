from app import create_app
from app.config.loader import load_settings

app = create_app()

if __name__ == "__main__":
    settings = load_settings()
    app.run(
        host=settings["app"]["host"],
        port=settings["app"]["port"],
        debug=settings["app"]["debug"],
    )
