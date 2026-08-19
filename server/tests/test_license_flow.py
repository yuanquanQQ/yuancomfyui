import base64
import json
from datetime import datetime

from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def decode_part(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_receipt(receipt: str, public_pem: str) -> dict:
    encoded_body, encoded_signature = receipt.split(".", 1)
    body = decode_part(encoded_body)
    signature = decode_part(encoded_signature)
    public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
    public_key.verify(signature, body)
    return json.loads(body)


def build_client(tmp_path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'license.db').as_posix()}",
        jwt_secret="j" * 64,
        card_hash_pepper="p" * 64,
        signing_key_path=tmp_path / "license_ed25519.pem",
        bootstrap_admin_username="admin",
        bootstrap_admin_password="Correct-Horse-2026",
    )
    return TestClient(create_app(settings))


def admin_headers(client):
    response = client.post("/api/admin/login", json={
        "username": "admin", "password": "Correct-Horse-2026"
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def generate_card(client, headers, plan="monthly"):
    response = client.post("/api/admin/cards/generate", headers=headers, json={
        "plan_type": plan, "count": 1, "device_limit": 1, "offline_grace_hours": 72
    })
    assert response.status_code == 200, response.text
    return response.json()["codes"][0]


def activation(code, machine="machine-hash-aaaaaaaa", install="install-id-aaaaaaaa"):
    return {
        "code": code, "machine_hash": machine, "install_id": install,
        "device_label": "Test PC", "app_version": "1.0.0",
    }


def check_payload(license_data, machine="machine-hash-aaaaaaaa", install="install-id-aaaaaaaa"):
    return {
        "license_id": license_data["license_id"],
        "refresh_token": license_data["refresh_token"],
        "machine_hash": machine, "install_id": install, "app_version": "1.0.1",
    }


def test_complete_license_lifecycle(tmp_path):
    with build_client(tmp_path) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        headers = admin_headers(client)
        card = generate_card(client, headers)

        activated_response = client.post("/api/v1/license/activate", json=activation(card))
        assert activated_response.status_code == 200, activated_response.text
        activated = activated_response.json()
        assert activated["status"] == "active"
        assert activated["refresh_token"]

        public_key = client.get("/api/v1/license/public-key").json()["public_key_pem"]
        receipt = verify_receipt(activated["signed_receipt"], public_key)
        assert receipt["license_id"] == activated["license_id"]
        assert receipt["machine_hash"] == "machine-hash-aaaaaaaa"

        duplicate = client.post("/api/v1/license/activate", json=activation(card))
        assert duplicate.status_code == 409

        wrong_machine = check_payload(activated, machine="machine-hash-bbbbbbbb")
        assert client.post("/api/v1/license/check", json=wrong_machine).status_code == 403
        checked = client.post("/api/v1/license/check", json=check_payload(activated))
        assert checked.status_code == 200
        assert checked.json()["refresh_token"] is None

        catalog = client.post(
            "/api/v1/license/workflows", json=check_payload(activated)
        )
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["default_workflow_key"] == "person_replace"
        assert len(catalog.json()["workflows"]) == 16
        assert all(item["key"] != "qwen_tryon" for item in catalog.json()["workflows"])

        renewal_card = generate_card(client, headers, "quarterly")
        original_expiry = datetime.fromisoformat(activated["expires_at"])
        renewal_payload = {**check_payload(activated), "code": renewal_card}
        renewed_response = client.post("/api/v1/license/renew", json=renewal_payload)
        assert renewed_response.status_code == 200, renewed_response.text
        renewed_expiry = datetime.fromisoformat(renewed_response.json()["expires_at"])
        assert (renewed_expiry - original_expiry).days == 90

        license_id = activated["license_id"]
        disabled = client.post(
            f"/api/admin/licenses/{license_id}/action", headers=headers,
            json={"action": "disable"},
        )
        assert disabled.status_code == 200
        assert client.post("/api/v1/license/check", json=check_payload(activated)).status_code == 403
        client.post(
            f"/api/admin/licenses/{license_id}/action", headers=headers,
            json={"action": "enable"},
        )

        rebind_response = client.post(
            f"/api/admin/licenses/{license_id}/rebind-code", headers=headers, json={}
        )
        assert rebind_response.status_code == 200
        rebound_response = client.post("/api/v1/license/activate", json=activation(
            rebind_response.json()["code"], "machine-hash-cccccccc", "install-id-cccccccc"
        ))
        assert rebound_response.status_code == 200, rebound_response.text
        assert client.post("/api/v1/license/check", json=check_payload(activated)).status_code == 401
        rebound = rebound_response.json()
        assert client.post("/api/v1/license/check", json=check_payload(
            rebound, "machine-hash-cccccccc", "install-id-cccccccc"
        )).status_code == 200

        cards = client.get("/api/admin/cards", headers=headers).json()
        assert cards["total"] == 2
        licenses = client.get("/api/admin/licenses", headers=headers).json()
        assert licenses["total"] == 1
        assert len(licenses["items"][0]["devices"]) == 2


def test_permanent_card_has_no_expiry(tmp_path):
    with build_client(tmp_path) as client:
        headers = admin_headers(client)
        card = generate_card(client, headers, "permanent")
        response = client.post("/api/v1/license/activate", json=activation(card))
        assert response.status_code == 200
        assert response.json()["expires_at"] is None
        assert response.json()["plan_type"] == "permanent"


def test_admin_can_change_password(tmp_path):
    with build_client(tmp_path) as client:
        headers = admin_headers(client)
        response = client.post("/api/admin/password", headers=headers, json={
            "current_password": "Correct-Horse-2026",
            "new_password": "New-Correct-Horse-2026",
        })
        assert response.status_code == 200
        assert client.post("/api/admin/login", json={
            "username": "admin", "password": "Correct-Horse-2026"
        }).status_code == 401
        assert client.post("/api/admin/login", json={
            "username": "admin", "password": "New-Correct-Horse-2026"
        }).status_code == 200


def test_custom_card_requires_duration_and_void_is_final(tmp_path):
    with build_client(tmp_path) as client:
        headers = admin_headers(client)
        missing_duration = client.post("/api/admin/cards/generate", headers=headers, json={
            "plan_type": "custom", "count": 1
        })
        assert missing_duration.status_code == 422

        card = generate_card(client, headers)
        item = client.get("/api/admin/cards", headers=headers).json()["items"][0]
        assert client.patch(f"/api/admin/cards/{item['id']}", headers=headers, json={
            "action": "void"
        }).status_code == 200
        assert client.patch(f"/api/admin/cards/{item['id']}", headers=headers, json={
            "action": "enable"
        }).status_code == 409
        assert client.post("/api/v1/license/activate", json=activation(card)).status_code == 409
