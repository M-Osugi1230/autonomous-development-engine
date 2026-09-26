from __future__ import annotations

import copy
import unittest

from ade import (
    ProviderCapability,
    ProviderDescriptor,
    ProviderRegistration,
    ProviderRegistry,
    RoutingRequest,
)


class FakeProvider:
    def list_sources(self):
        return []

    def create_session(self, **kwargs):
        return {"id": "fake"}

    def get_session(self, session_id):
        return {"state": "COMPLETED"}

    def list_activities(self, session_id):
        return []

    def send_message(self, session_id, prompt):
        return None

    def approve_plan(self, session_id):
        return None


def descriptor(
    provider_id: str,
    *,
    priority: int = 100,
    enabled: bool = True,
    capabilities=(),
):
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name=provider_id,
        capabilities=tuple(capabilities),
        priority=priority,
        enabled=enabled,
    )


class ProviderRegistryTests(unittest.TestCase):
    def test_duplicate_provider_ids_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ProviderRegistry(
                (
                    ProviderRegistration(descriptor("a"), FakeProvider()),
                    ProviderRegistration(descriptor("a"), FakeProvider()),
                )
            )

    def test_disabled_provider_is_not_candidate(self) -> None:
        registry = ProviderRegistry.from_pairs(
            (
                (descriptor("a", enabled=False), FakeProvider()),
                (descriptor("b"), FakeProvider()),
            )
        )
        candidates = registry.candidates(RoutingRequest())
        self.assertEqual(
            [item.provider_id for item in candidates],
            ["b"],
        )

    def test_required_capabilities_filter_candidates(self) -> None:
        registry = ProviderRegistry.from_pairs(
            (
                (
                    descriptor(
                        "basic",
                        capabilities=(ProviderCapability.GITHUB_SOURCE,),
                    ),
                    FakeProvider(),
                ),
                (
                    descriptor(
                        "pr",
                        capabilities=(
                            ProviderCapability.GITHUB_SOURCE,
                            ProviderCapability.AUTO_CREATE_PR,
                        ),
                    ),
                    FakeProvider(),
                ),
            )
        )
        request = RoutingRequest(
            required_capabilities=(
                ProviderCapability.GITHUB_SOURCE,
                ProviderCapability.AUTO_CREATE_PR,
            )
        )
        self.assertEqual(
            [item.provider_id for item in registry.candidates(request)],
            ["pr"],
        )

    def test_allowlist_filtering(self) -> None:
        registry = ProviderRegistry.from_pairs(
            (
                (descriptor("a"), FakeProvider()),
                (descriptor("b"), FakeProvider()),
                (descriptor("c"), FakeProvider()),
            )
        )
        request = RoutingRequest(allowed_provider_ids=("c", "a"))
        self.assertEqual(
            [item.provider_id for item in registry.candidates(request)],
            ["a", "c"],
        )

    def test_preference_order_overrides_fallback_priority(self) -> None:
        registry = ProviderRegistry.from_pairs(
            (
                (descriptor("a", priority=1), FakeProvider()),
                (descriptor("b", priority=50), FakeProvider()),
                (descriptor("c", priority=10), FakeProvider()),
            )
        )
        request = RoutingRequest(
            preferred_provider_ids=("b", "c"),
        )
        self.assertEqual(
            [item.provider_id for item in registry.candidates(request)],
            ["b", "c", "a"],
        )

    def test_fallback_order_is_priority_then_provider_id(self) -> None:
        registry = ProviderRegistry.from_pairs(
            (
                (descriptor("z", priority=20), FakeProvider()),
                (descriptor("b", priority=10), FakeProvider()),
                (descriptor("a", priority=10), FakeProvider()),
            )
        )
        self.assertEqual(
            [item.provider_id for item in registry.candidates(RoutingRequest())],
            ["a", "b", "z"],
        )

    def test_descriptor_snapshot_contains_no_provider_object(self) -> None:
        registry = ProviderRegistry.from_pairs(
            ((descriptor("a"), FakeProvider()),)
        )
        snapshot = registry.descriptor_snapshot()
        self.assertEqual(snapshot[0]["provider_id"], "a")
        self.assertNotIn("provider", snapshot[0])

    def test_provider_instance_must_match_protocol_shape(self) -> None:
        with self.assertRaises(ValueError):
            ProviderRegistration(descriptor("a"), object())

    def test_input_collections_are_not_mutated(self) -> None:
        pairs = [
            (descriptor("b", priority=20), FakeProvider()),
            (descriptor("a", priority=10), FakeProvider()),
        ]
        before_ids = [item[0].provider_id for item in pairs]
        registry = ProviderRegistry.from_pairs(pairs)
        registry.candidates(RoutingRequest())
        self.assertEqual(
            [item[0].provider_id for item in pairs],
            before_ids,
        )

    def test_get_require_and_registration_repr_do_not_leak_provider(self) -> None:
        provider = FakeProvider()
        registry = ProviderRegistry.from_pairs(
            ((descriptor("a"), provider),)
        )
        registration = registry.require("a")
        self.assertIs(registration.provider, provider)
        self.assertEqual(registration.provider_id, "a")
        self.assertNotIn("FakeProvider", repr(registration))
        self.assertIsNone(registry.get("missing"))
        with self.assertRaises(KeyError):
            registry.require("missing")


if __name__ == "__main__":
    unittest.main()
