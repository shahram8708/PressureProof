from app import create_app


application = create_app("production")


if __name__ == "__main__":
    application.run(use_reloader=False)

# Provide a common WSGI variable name expected by some deploy commands
app = application
