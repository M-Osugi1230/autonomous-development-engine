from __future__ import annotations

import unittest

from ade.production_provider_broker import (
    BrokerAvailability,
    COPILOT_PROVIDER_ID,
    JULES_PROVIDER_ID,
    checkpoint_provider_id,
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


class ProductionProviderBrokerTests(unittest.TestCase):
    def registry(self) -> ProviderRegistry:
        fake = FakeProvider()
        descriptors = provider_descriptors()
        return ProviderRegistry.from_pairs(
            [(descriptors[0], fake), (descriptors[1], fake)]
        )

    def test_prefers_jules_when_jules_has_capacity(self) -> None:
        decision = route_implementation_provider(
            self.registry(),
            availability=BrokerAvailability(
                jules_available=True,
                copilot_available=True,
            ),
        )
        self.assertEqual(decision.selected_provider_id, JULES_PROVIDER_ID)

    def test_falls_back_to_copilot_when_jules_is_quota_paused(self) -> None:
        decision = route_implementation_provider(
            self.registry(),
            availability=BrokerAvailability(
                jules_available=False,
                copilot_available=True,
                jules_reason="global-limit-exhausted",
            ),
        )
        self.assertEqual(decision.selected_provider_id, COPILOT_PROVIDER_ID)

    def test_no_provider_when_jules_paused_and_copilot_disabled(self) -> None:
        decision = route_implementation_provider(
            self.registry(),
            availability=BrokerAvailability(
                jules_available=False,
                copilot_available=False,
            ),
        )
        self.assertIsNone(decision.selected_provider_id)

    def test_old_checkpoint_with_session_defaults_to_jules(self) -> None:
        self.assertEqual(
            checkpoint_provider_id(
                {
                    "provider_session_id": "legacy-session",
                    "state": "RUNNING",
                }
            ),
            JULES_PROVIDER_ID,
        )

    def test_new_checkpoint_preserves_explicit_provider(self) -> None:
        self.assertEqual(
            checkpoint_provider_id(
                {
                    "provider_session_id": "task-123",
                    "provider_id": COPILOT_PROVIDER_ID,
                    "state": "RUNNING",
                }
            ),
            COPILOT_PROVIDER_ID,
        )

    def test_copilot_requires_token_and_explicit_cost_opt_in(self) -> None:
        self.assertFalse(
            copilot_fallback_enabled(token="token", explicit_enable=None)
        )
        self.assertFalse(
            copilot_fallback_enabled(token=None, explicit_enable="true")
        )
        self.assertTrue(
            copilot_fallback_enabled(token="token", explicit_enable="true")
        )


if __name__ == "__main__":
    unittest.main()
