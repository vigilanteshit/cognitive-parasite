from fastapi.testclient import TestClient

from data_parasite.api import create_app
from data_parasite.config import ModelProfile, Settings


def client_at(tmp_path):
    return TestClient(
        create_app(
            Settings(_env_file=None, data_dir=tmp_path, models_file=tmp_path / "absent.toml")
        ),
        base_url="http://localhost",
    )


def test_demo_chat_roundtrip_and_persistence(tmp_path):
    with client_at(tmp_path) as client:
        session = client.post("/api/sessions", json={}).json()
        run = client.post(
            f"/api/sessions/{session['id']}/runs",
            json={"message": "Hello", "model_profile": "demo"},
        ).json()
        events = client.get(f"/api/runs/{run['id']}/events").text
        assert '"type": "done"' in events
        assert '"status": "completed"' in events
        assert "Local demo" in events
    with client_at(tmp_path) as client:
        stored = client.get(f"/api/sessions/{session['id']}").json()
        assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]


def test_unknown_model_and_host_are_rejected(tmp_path):
    with client_at(tmp_path) as client:
        session = client.post("/api/sessions", json={}).json()
        response = client.post(
            f"/api/sessions/{session['id']}/runs",
            json={"message": "Hello", "model_profile": "missing"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_model"
        assert client.get("/api/health", headers={"host": "attacker.example"}).status_code == 400
        assert (
            client.post(
                "/api/sessions", json={}, headers={"origin": "https://attacker.example"}
            ).status_code
            == 403
        )


def test_ingestion_and_session_isolation(tmp_path):
    with client_at(tmp_path) as client:
        first = client.post("/api/sessions", json={}).json()["id"]
        second = client.post("/api/sessions", json={}).json()["id"]
        payload = {
            "session_id": first,
            "title": "Synthetic manual",
            "text": "The training pump needs a check every twelve months.",
        }
        assert client.post("/api/documents", json=payload).status_code == 201
        assert len(client.get(f"/api/sessions/{first}/memories").json()["memories"]) == 1
        assert client.get(f"/api/sessions/{second}/memories").json()["memories"] == []
        assert client.post("/api/documents", json=payload).status_code == 201
        assert len(client.get(f"/api/sessions/{first}/memories").json()["memories"]) == 1


def test_validation_does_not_echo_sensitive_input(tmp_path):
    with client_at(tmp_path) as client:
        response = client.post(
            "/api/documents", json={"session_id": "missing", "title": "private", "text": ""}
        )
        assert response.status_code == 422
        assert "private" not in response.text


def test_resume_can_switch_to_larger_compatible_profile(tmp_path):
    with client_at(tmp_path) as client:
        client.app.state.router.profiles["demo"] = ModelProfile(
            id="demo", provider="demo", model="demo", context_window=2048, max_output_tokens=128
        )
        client.app.state.router.profiles["wide"] = ModelProfile(
            id="wide", provider="demo", model="demo", context_window=16384
        )
        session = client.post("/api/sessions", json={}).json()["id"]
        run = client.post(
            f"/api/sessions/{session}/runs", json={"message": "x" * 2200, "model_profile": "demo"}
        ).json()
        assert '"status": "limited"' in client.get(f"/api/runs/{run['id']}/events").text
        resumed = client.post(
            f"/api/runs/{run['id']}/resume", json={"model_profile": "wide"}
        ).json()
        events = client.get(f"/api/runs/{run['id']}/events?after={resumed['event_cursor']}").text
        assert '"status": "completed"' in events
        assert client.app.state.store.find_run(run["id"])["model_profile"] == "wide"
