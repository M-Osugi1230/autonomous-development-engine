from __future__ import annotations

import remote_pr_monitor as base_monitor
from target_runtime_profile import (
    build_runtime_probe_registry,
    build_runtime_verification_policy,
)


def main() -> int:
    base_monitor.build_runtime_probe_registry = build_runtime_probe_registry
    base_monitor.build_runtime_verification_policy = build_runtime_verification_policy
    return base_monitor.main()


if __name__ == "__main__":
    raise SystemExit(main())
