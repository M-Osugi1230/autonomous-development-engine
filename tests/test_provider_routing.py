from __future__ import annotations

import copy
import unittest

from ade.provider_routing import (
    ProviderCapability,
    ProviderCostClass,
    ProviderDescriptor,
    RoutingRequest,
)


class ProviderDescriptorTests(unittest.TestCase):
    def test_round_trip_and_deterministic_capability_order(self) -> None:
        descriptor = ProviderDescriptor(
            provider_id="jules",
            display_name="Google Jules",
            capabilities=(
                ProviderCapability.RESUME_SESSION,
                ProviderCapability.GITHUB_SOURCE,
                ProviderCapability.AUTO_CREATE_PR,
            ),
            priority=10,
            enabled=True,
            cost_class=ProviderCostClass.FLAT_RATE,
        )

        self.assertEqual(
            descriptor.capabilities,
            (
                ProviderCapability.AUTO_CREATE_PR,
                ProviderCapability.GITHUB_SOURCE,
                ProviderCapability.RESUME_SESSION,
            ),
        )
        restored = ProviderDescriptor.from_dict(descriptor.to_dict())
        self.assertEqual(restored, descriptor)

    def test_invalid_and_duplicate_capabilities_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ProviderDescriptor(
                provider_id="jules",
                display_name="Jules",
                capabilities=(
                    ProviderCapability.GITHUB_SOURCE,
                    ProviderCapability.GITHUB_SOURCE,
                ),
            )
        with self.assertRaises(ValueError):
            ProviderDescriptor(
                provider_id="jules",
                display_name="Jules",
                capabilities=("NOT_A_CAPABILITY",),
            )

    def test_provider_id_is_stable_and_lowercase_safe(self) -> None:
        descriptor = ProviderDescriptor(
            provider_id="provider.one",
            display_name="Provider One",
            capabilities=(),
        )
        self.assertEqual(descriptor.provider_id, "provider.one")

        for invalid in ("Provider", " provider", "provider/one", "", "1provider"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    ProviderDescriptor(
                        provider_id=invalid,
                        display_name="Provider",
                        capabilities=(),
                    )

    def test_priority_enabled_and_cost_validation(self) -> None:
        with self.assertRaises(ValueError):
            ProviderDescriptor(
                provider_id="p",
                display_name="P",
                capabilities=(),
                priority=-1,
            )
        with self.assertRaises(ValueError):
            ProviderDescriptor(
                provider_id="p",
                display_name="P",
                capabilities=(),
                enabled=1,  # type: ignore[arg-type]
            )
        with self.assertRaises(ValueError):
            ProviderDescriptor(
                provider_id="p",
                display_name="P",
                capabilities=(),
                cost_class="INVALID",  # type: ignore[arg-type]
            )

    def test_supports_validates_capability(self) -> None:
        descriptor = ProviderDescriptor(
            provider_id="p",
            display_name="P",
            capabilities=(ProviderCapability.GITHUB_SOURCE,),
        )
        self.assertTrue(descriptor.supports(ProviderCapability.GITHUB_SOURCE))
        self.assertFalse(descriptor.supports(ProviderCapability.AUTO_CREATE_PR))
        with self.assertRaises(ValueError):
            descriptor.supports("INVALID")


class RoutingRequestTests(unittest.TestCase):
    def test_round_trip_and_preference_order_preserved(self) -> None:
        request = RoutingRequest(
            required_capabilities=(
                ProviderCapability.RESUME_SESSION,
                ProviderCapability.GITHUB_SOURCE,
            ),
            allowed_provider_ids=("jules", "backup"),
            preferred_provider_ids=("backup", "jules"),
        )
        self.assertEqual(
            request.required_capabilities,
            (
                ProviderCapability.GITHUB_SOURCE,
                ProviderCapability.RESUME_SESSION,
            ),
        )
        self.assertEqual(request.preferred_provider_ids, ("backup", "jules"))
        self.assertEqual(RoutingRequest.from_dict(request.to_dict()), request)

    def test_preferred_must_be_allowed_when_allowlist_exists(self) -> None:
        with self.assertRaises(ValueError):
            RoutingRequest(
                allowed_provider_ids=("jules",),
                preferred_provider_ids=("backup",),
            )

    def test_duplicate_provider_ids_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RoutingRequest(
                allowed_provider_ids=("jules", "jules"),
            )
        with self.assertRaises(ValueError):
            RoutingRequest(
                preferred_provider_ids=("jules", "jules"),
            )

    def test_caller_inputs_are_not_mutated(self) -> None:
        payload = {
            "required_capabilities": [
                ProviderCapability.RESUME_SESSION.value,
                ProviderCapability.GITHUB_SOURCE.value,
            ],
            "allowed_provider_ids": ["jules", "backup"],
            "preferred_provider_ids": ["backup"],
        }
        before = copy.deepcopy(payload)
        request = RoutingRequest.from_dict(payload)
        self.assertEqual(payload, before)

        round_trip = request.to_dict()
        round_trip["required_capabilities"].append("AUTO_CREATE_PR")
        self.assertNotIn(
            ProviderCapability.AUTO_CREATE_PR,
            request.required_capabilities,
        )

    def test_invalid_payload_shapes_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RoutingRequest.from_dict([])  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            RoutingRequest.from_dict({"required_capabilities": "x"})
        with self.assertRaises(ValueError):
            RoutingRequest.from_dict({"allowed_provider_ids": "jules"})
        with self.assertRaises(ValueError):
            RoutingRequest.from_dict({"preferred_provider_ids": "jules"})


if __name__ == "__main__":
    unittest.main()
