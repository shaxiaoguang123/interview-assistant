from app import create_app
from app.services.ingestion import recover_interrupted_jobs


def main() -> None:
    app = create_app()
    session_factory = app.extensions["sqlalchemy_session_factory"]
    recover_interrupted_jobs(session_factory)
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=bool(app.config.get("DEBUG", False)),
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
