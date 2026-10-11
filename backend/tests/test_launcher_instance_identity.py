import json
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.maintenance.instance_identity import (
    ensure_instance_id,
    status_matches_instance,
)


def test_instance_id_is_stable_and_stored_with_private_permissions(tmp_path):
    data_dir = tmp_path / "app-data"

    first = ensure_instance_id(data_dir)
    second = ensure_instance_id(data_dir)

    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert (data_dir / ".launcher" / "instance-id").stat().st_mode & 0o777 == 0o600


def test_simultaneous_launchers_publish_one_complete_instance_id(tmp_path):
    data_dir = tmp_path / "racing-app-data"

    with ThreadPoolExecutor(max_workers=8) as pool:
        instance_ids = list(pool.map(lambda _index: ensure_instance_id(data_dir), range(8)))

    assert len(set(instance_ids)) == 1


def test_status_matches_only_the_expected_agent_assistant_instance():
    own_id = "a" * 64
    other_id = "b" * 64
    status = {
        "application": "agent-interview-assistant",
        "launcher": {"instance_id": own_id},
    }

    assert status_matches_instance(json.dumps(status), own_id)
    assert not status_matches_instance(json.dumps({**status, "launcher": {"instance_id": other_id}}), own_id)
    assert not status_matches_instance('{"application":"agent-interview-assistant"}', own_id)
    assert not status_matches_instance("not-json", own_id)


def test_instance_id_refuses_symlinked_state_directory_or_file(tmp_path):
    data_dir = tmp_path / "app-data"
    launcher = data_dir / ".launcher"
    launcher.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (launcher / "instance-id").symlink_to(outside / "id")

    with pytest.raises(RuntimeError):
        ensure_instance_id(data_dir)


def test_system_status_exposes_only_the_opaque_launcher_instance_id(client, app):
    instance_id = "c" * 64
    app.config["APP_INSTANCE_ID"] = instance_id

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    result = response.get_json()
    assert result["launcher"]["instance_id"] == instance_id
    assert "APP_DATA_DIR" not in response.get_data(as_text=True)
