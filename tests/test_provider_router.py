from __future__ import annotations

import unittest

from ade import (
    ProviderAvailability,
    ProviderAvailabilitySnapshot,
    ProviderCapability,
    ProviderDescriptor,
    ProviderRegistration,
    ProviderRegistry,
    RoutingOutcome,
    RoutingRequest,
    route_provider,
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
    priority: int,
    enabled: bool = True,
):
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name=provider_id,
        capabilities=(
            ProviderCapability.GITHUB_SOURCE,
            ProviderCapability.AUTO_CREATE_PR,
        ),
        priority=priority,
        enabled=enabled,
    )


def registry():
    return ProviderRegistry(
        (
            ProviderRegistration(descriptor("primary", priority=10), FakeProvider()),
            ProviderRegistration(descriptor("backup", priority=20), FakeProvider()),
            ProviderRegistration(
                descriptor("disabled", priority=1, enabled=False),
                FakeProvider(),
            ),
        )
    )


class ProviderRouterTests(unittest.TestCase):
    def test_preferred_available_provider_is_selected(self) -> None:
        decision = route_provider(
            registry(),
            RoutingRequest(preferred_provider_ids=("backup",)),
            (
                ProviderAvailabilitySnapshot(
                    "primary",
                    ProviderAvailability.AVAILABLE,
                ),
                ProviderAvailabilitySnapshot(
                    "backup",
                    ProviderAvailability.AVAILABLE,
                ),
            ),
        )
        self.assertEqual(decision.outcome, RoutingOutcome.SELECTED)
        self.assertEqual(decision.selected_provider_id, "backup")
        self.assertEqual(
            decision.candidate_provider_ids,
            ("backup", "primary"),
        )

    def test_quota_paused_provider_falls_back(self) -> None:
        decision = route_provider(
            registry(),
            RoutingRequest(),
            (
                ProviderAvailabilitySnapshot(
                    "primary",
                    ProviderAvailability.QUOTA_PAUSED,
                    "rolling quota",
                ),
                ProviderAvailabilitySnapshot(
                    "backup",
                    ProviderAvailability.AVAILABLE,
                ),
            ),
        )
        self.assertEqual(decision.selected_provider_id, "backup")
        self.assertEqual(len(decision.skipped), 1)
        self.assertEqual(
            decision.skipped[0].availability,
            ProviderAvailability.QUOTA_PAUSED,
        )

    def test_temporarily_unavailable_provider_falls_back(self) -> None:
        decision = route_provider(
            registry(),
            RoutingRequest(),
            (
                ProviderAvailabilitySnapshot(
                    "primary",
                    ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                ),
                ProviderAvailabilitySnapshot(
                    "backup",
                    ProviderAvailability.AVAILABLE,
                ),
            ),
        )
        self.assertEqual(decision.selected_provider_id, "backup")

    def test_unauthorized_provider_is_never_selected(self) -> None:
        decision = route_provider(
            registry(),
            RoutingRequest(preferred_provider_ids=("primary",)),
            (
                ProviderAvailabilitySnapshot(
                    "primary",
                    ProviderAvailability.UNAUTHORIZED,
                    "authentication failed",
                ),
                ProviderAvailabilitySnapshot(
                    "backup",
                    ProviderAvailability.AVAILABLE,
                ),
            ),
        )
        self.assertEqual(decision.selected_provider_id, "backup")
        self.assertEqual(
            decision.skipped[0].availability,
            ProviderAvailability.UNAUTHORIZED,
        )

    def test_disabled_descriptor_is_never_candidate(self) -> None:
        decision = route_provider(
            registry(),
            RoutingRequest(),
            (
                ProviderAvailabilitySnapshot(
                    "disabled",
                    ProviderAvailability.AVAILABLE,
                ),
                ProviderAvailabilitySnapshot(
                    "primary",
                    ProviderAvailability.AVAILABLE,
                ),
                ProviderAvailabilitySnapshot(
                    "backup",
                    ProviderAvailability.AVAILABLE,
                ),
            ),
        )
        self.assertNotIn("disabled", decision.candidate_provider_ids)
        self.assertNotEqual(decision.selected_provider_id, "disabled")

    def test_no_candidate_returns_explicit_decision(self) -> None:
        decision = route_provider(
            registry(),
            RoutingRequest(
                required_capabilities=(
                    ProviderCapability.RESUME_SESSION,
                )
            ),
            (),
        )
        self.assertEqual(decision.outcome, RoutingOutcome.NO_PROVIDER)
        self.assertIsNone(decision.selected_provider_id)
        self.assertEqual(decision.candidate_provider_ids, ())
        self.assertIn("no providers satisfy", decision.reason)

    def test_missing_snapshot_is_not_assumed_available(self) -> None:
        decision = route_provider(
            registry(),
            RoutingRequest(allowed_provider_ids=("primary",)),
            (),
        )
        self.assertEqual(decision.outcome, RoutingOutcome.NO_PROVIDER)
        self.assertEqual(
            decision.skipped[0].availability,
            ProviderAvailability.TEMPORARILY_UNAVAILABLE,
        )

    def test_repeated_selection_is_deterministic(self) -> None:
        request = RoutingRequest()
        snapshots = (
            ProviderAvailabilitySnapshot(
                "primary",
                ProviderAvailability.QUOTA_PAUSED,
            ),
            ProviderAvailabilitySnapshot(
                "backup",
                ProviderAvailability.AVAILABLE,
            ),
        )
        first = route_provider(registry(), request, snapshots)
        second = route_provider(registry(), request, snapshots)
        self.assertEqual(first, second)

    def test_duplicate_snapshot_rejected(self) -> None:
        with self.assertRaises(ValueError):
            route_provider(
                registry(),
                RoutingRequest(),
                (
                    ProviderAvailabilitySnapshot(
                        "primary",
                        ProviderAvailability.AVAILABLE,
                    ),
                    ProviderAvailabilitySnapshot(
                        "primary",
                        ProviderAvailability.AVAILABLE,
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
