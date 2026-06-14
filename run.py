import os

from app import create_app


env_name = os.getenv("FLASK_ENV", "development")
app = create_app(env_name)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=env_name == "development",
        use_reloader=False,
    )
