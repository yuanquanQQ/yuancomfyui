import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from license_client import (
    LicenseManager,
    _dpapi_protect,
    _dpapi_unprotect,
    _utcnow,
    machine_hash,
)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from app.security import ReceiptSigner


class LicenseClientTests(unittest.TestCase):
    def test_protected_token_round_trip(self):
        encrypted = _dpapi_protect("refresh-token-secret")
        self.assertNotIn("refresh-token-secret", encrypted)
        self.assertEqual("refresh-token-secret", _dpapi_unprotect(encrypted))

    def test_activation_verifies_signature_and_never_saves_raw_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = LicenseManager(root / "state", "http://127.0.0.1:8088")
            signer = ReceiptSigner(root / "signing.pem", "test-key")
            license_id = "test-license-id"
            now = _utcnow()
            payload = {
                "license_id": license_id,
                "machine_hash": machine_hash(),
                "plan_type": "permanent",
                "status": "active",
                "expires_at": None,
                "offline_until": (now + timedelta(hours=72)).isoformat(),
                "server_time": now.isoformat(),
                "key_id": "test-key",
                "device_limit": 1,
            }
            activation = {
                "license_id": license_id,
                "status": "active",
                "plan_type": "permanent",
                "expires_at": None,
                "offline_until": payload["offline_until"],
                "server_time": payload["server_time"],
                "device_limit": 1,
                "refresh_token": "raw-refresh-token-must-not-be-saved",
                "signed_receipt": signer.sign(payload),
            }

            def fake_request(method, path, payload=None):
                if path.endswith("public-key"):
                    return {
                        "algorithm": "Ed25519",
                        "key_id": "test-key",
                        "public_key_pem": signer.public_key_pem(),
                    }
                return activation

            with mock.patch.object(manager, "_request", side_effect=fake_request):
                status = manager.activate("YCF-PERM-TEST-CARD")

            self.assertTrue(status["active"])
            saved_text = manager.state_path.read_text(encoding="utf-8")
            self.assertNotIn("raw-refresh-token-must-not-be-saved", saved_text)
            saved = json.loads(saved_text)
            self.assertTrue(saved["refresh_token_protected"].startswith(("dpapi:", "local:")))


if __name__ == "__main__":
    unittest.main()
