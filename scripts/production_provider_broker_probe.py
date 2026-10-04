from __future__ import annotations

import json

from ade.production_provider_broker import (
    BrokerAvailability,
    COPILOT_PROVIDER_ID,
    JULES_PROVIDER_ID,
    copilot_fallback_enabled,
    provider_descriptors,
    route_implementation_provider,
)
from ade.provider_registry import ProviderRegistry


class FakeProvider:
    def list_sources(self):
        return []

    def create_session(self, **kwargs):
        return {"id": "fake"}

    def get_session(self, session_id):
        return {"id": session_id, "state": "COMPLETED", "outputs": []}

    def list_activities(self, session_id):
        return []

    def send_message(self, session_id, prompt):
        return None

    def approve_plan(self, session_id):
        return None


def run_probe() -> dict[str, object]:
    descriptors = provider_descriptors()
    fake = FakeProvider()
    registry = ProviderRegistry.from_pairs(
        [(descriptors[0], fake), (descriptors[1], fake)]
    )
    normal = route_implementation_provider(
        registry,
        availability=BrokerAvailability(
            jules_available=True,
            copilot_available=True,
        ),
    )
    fallback = route_implementation_provider(
        registry,
        availability=BrokerAvailability(
            jules_available=False,
            copilot_available=True,
            jules_reason="quota",
        ),
    )
    guarded = route_implementation_provider(
        registry,
        availability=BrokerAvailability(
            jules_available=False,
            copilot_available=False,
            jules_reason="quota",
            copilot_reason="explicit-opt-in-required",
        ),
    )
    if normal.selected_provider_id != JULES_PROVIDER_ID:
        raise AssertionError("Jules was not preferred")
    if fallback.selected_provider_id != COPILOT_PROVIDER_ID:
        raise AssertionError("Copilot was not selected as fallback")
    if guarded.selected_provider_id is not None:
        raise AssertionError("cost guard did not disable Copilot")
    if copilot_fallback_enabled(
        token="token",
        explicit_enable="",
    ):
        raise AssertionError("Copilot activated without explicit opt-in")
    return {
        "ok": True,
        "preferred": JULES_PROVIDER_ID,
        "quota_fallback": COPILOT_PROVIDER_ID,
        "cost_guard_default": "disabled",
    }


def main() -> int:
    try:
        result = run_probe()
    except Exception as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(json.dumps({"ok": False, "error": message[:256]}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
