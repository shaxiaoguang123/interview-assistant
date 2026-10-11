import os
from contextlib import nullcontext

from app import create_app
from app.services.ingestion import recover_interrupted_jobs
from app.services.source_storage import recover_source_tombstones
from app.maintenance.service_lock import claim_service_lock


def main() -> None:
    app = create_app()
    session_factory = app.extensions["sqlalchemy_session_factory"]
    service_guard = claim_service_lock(app.config["APP_DATA_DIR"]) if app.config.get("APP_DATA_DIR") else nullcontext()
    with service_guard:
        recover_interrupted_jobs(session_factory)
        recover_source_tombstones(session_factory, app.config["SOURCE_STORAGE_DIR"])
        app.run(
            host="127.0.0.1",
            port=int(os.environ.get("APP_PORT", "5000")),
            debug=bool(app.config.get("DEBUG", False)),
            use_reloader=False,
        )


if __name__ == "__main__":
    main()
