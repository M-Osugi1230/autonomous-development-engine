from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_jules_client():
    path = TRUSTED_DIR / "jules_client.py"
    spec = importlib.util.spec_from_file_location("trusted_jules_client_test_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load trusted jules_client.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_http_error(code: int, message: str) -> HTTPError:
    body = (
        '{"error":{"message":' + __import__("json").dumps(message) + "}}"
    ).encode("utf-8")
    return HTTPError(
        url="https://example.invalid/v1alpha/sessions",
        code=code,
        msg=message,
        hdrs=None,
        fp=io.BytesIO(body),
    )


class TrustedJulesClientTests(unittest.TestCase):
    def test_http_412_maps_to_precondition(self) -> None:
        module = load_jules_client()
        client = module.JulesClient(api_key="test-key", base_url="https://example.invalid")

        def failing_urlopen(*args, **kwargs):
            raise make_http_error(412, "Precondition check failed.")

        module.urlopen = failing_urlopen
        with self.assertRaises(module.JulesPrecondition) as ctx:
            client._request("POST", "sessions", payload={"prompt": "x"})
        self.assertIn("HTTP 412", str(ctx.exception))
        self.assertIn("Precondition check failed", str(ctx.exception))

    def test_http_429_maps_to_quota(self) -> None:
        module = load_jules_client()
        client = module.JulesClient(api_key="test-key", base_url="https://example.invalid")

        def failing_urlopen(*args, **kwargs):
            raise make_http_error(429, "Quota exceeded")

        module.urlopen = failing_urlopen
        with self.assertRaises(module.JulesQuota):
            client._request("GET", "sources")

    def test_http_403_maps_to_unauthorized(self) -> None:
        module = load_jules_client()
        client = module.JulesClient(api_key="test-key", base_url="https://example.invalid")

        def failing_urlopen(*args, **kwargs):
            raise make_http_error(403, "Forbidden")

        module.urlopen = failing_urlopen
        with self.assertRaises(module.JulesUnauthorized):
            client._request("GET", "sources")


if __name__ == "__main__":
    unittest.main()
