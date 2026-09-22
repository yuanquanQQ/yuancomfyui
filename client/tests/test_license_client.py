import json
import base64
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from license_client import (
    LicenseError,
    LicenseManager,
    _dpapi_protect,
    _dpapi_unprotect,
    machine_hash,
)
class LicenseClientTests(unittest.TestCase):
    def test_machine_hash_ignores_volatile_device_fields_when_machine_guid_exists(self):
        with mock.patch("license_client._windows_machine_guid", return_value="stable-guid"), \
                mock.patch("license_client._system_drive_serial", side_effect=["AAAA", "BBBB"]), \
                mock.patch("license_client.platform.node", side_effect=["PC-OLD", "PC-NEW"]), \
                mock.patch("license_client.uuid.getnode", side_effect=[1, 2]):
            first = machine_hash()
            second = machine_hash()

        self.assertEqual(first, second)

    def test_existing_installation_keeps_machine_hash_from_legacy_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            body = base64.urlsafe_b64encode(json.dumps({
                "machine_hash": "legacy-machine-hash",
            }).encode("utf-8")).decode("ascii").rstrip("=")
            (state_dir / "license_state.json").write_text(json.dumps({
                "install_id": "existing-install-id",
                "receipt": f"{body}.legacy-signature",
            }), encoding="utf-8")

            manager = LicenseManager(state_dir, "https://license.example")

            self.assertEqual("legacy-machine-hash", manager.state["machine_hash"])

    def test_protected_token_round_trip(self):
        encrypted = _dpapi_protect("refresh-token-secret")
        self.assertNotIn("refresh-token-secret", encrypted)
        self.assertEqual("refresh-token-secret", _dpapi_unprotect(encrypted))

    def test_activation_saves_only_online_credentials_and_not_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = LicenseManager(root / "state", "http://127.0.0.1:8088")
            license_id = "test-license-id"
            now = datetime.now(timezone.utc)
            activation = {
                "license_id": license_id,
                "status": "active",
                "plan_type": "permanent",
                "expires_at": None,
                "offline_until": (now + timedelta(hours=72)).isoformat(),
                "server_time": now.isoformat(),
                "device_limit": 1,
                "refresh_token": "raw-refresh-token-must-not-be-saved",
                "signed_receipt": "server-receipt-is-not-stored",
            }

            def fake_request(method, path, payload=None):
                return activation

            with mock.patch.object(manager, "_request", side_effect=fake_request):
                status = manager.activate("YCF-PERM-TEST-CARD")

            self.assertTrue(status["active"])
            saved_text = manager.state_path.read_text(encoding="utf-8")
            self.assertNotIn("raw-refresh-token-must-not-be-saved", saved_text)
            saved = json.loads(saved_text)
            self.assertTrue(saved["refresh_token_protected"].startswith(("dpapi:", "local:")))
            self.assertNotIn("receipt", saved)
            self.assertNotIn("public_key_pem", saved)

    def test_reset_preserves_installation_and_removes_server_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = LicenseManager(Path(directory) / "state", "https://license.example")
            install_id = manager.state["install_id"]
            manager.state.update({
                "license_id": "old-license",
                "refresh_token_protected": "dpapi:old-token",
                "public_key_pem": "old-public-key",
                "receipt": "old-receipt",
                "server_denied": True,
            })
            manager._save_state()

            status = manager.reset()

            self.assertFalse(status["active"])
            self.assertIsNone(status["license_id"])
            self.assertEqual(install_id, manager.state["install_id"])
            self.assertEqual(2, len(manager.state))
            self.assertIn("machine_hash", manager.state)

    def test_status_checks_online_on_every_online_request(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = LicenseManager(Path(directory) / "state", "https://license.example")
            manager.state.update({
                "license_id": "license-id",
                "receipt": "signed-receipt",
                "public_key_pem": "public-key",
            })
            manager._check_online = mock.Mock()

            manager.status(check_online=True)
            manager.status(check_online=True)
            manager.status(check_online=False)

            self.assertEqual(2, manager._check_online.call_count)

    def test_status_never_uses_local_receipt_when_server_is_unreachable(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = LicenseManager(Path(directory) / "state", "https://license.example")
            manager.state.update({
                "license_id": "license-id",
                "receipt": "signed-receipt",
                "public_key_pem": "public-key",
                "refresh_token_protected": _dpapi_protect("x" * 32),
            })
            manager._check_online = mock.Mock(
                side_effect=ConnectionError("license server unavailable")
            )

            status = manager.status(check_online=True)

            self.assertFalse(status["active"])
            self.assertEqual("online", status["mode"])
            self.assertFalse(status["requires_activation"])

    def test_only_expired_online_license_requires_reactivation(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = LicenseManager(Path(directory) / "state", "https://license.example")
            manager.state["license_id"] = "license-id"
            manager._check_online = mock.Mock(side_effect=LicenseError("授权已到期"))

            status = manager.status(check_online=True)

            self.assertFalse(status["active"])
            self.assertTrue(status["requires_activation"])

    def test_previous_denial_does_not_skip_the_next_online_check(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = LicenseManager(Path(directory) / "state", "https://license.example")
            manager.state.update({
                "license_id": "license-id",
                "server_denied": True,
                "last_error": "old rejection",
            })
            manager._check_online = mock.Mock()

            manager.status(check_online=True)

            manager._check_online.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
