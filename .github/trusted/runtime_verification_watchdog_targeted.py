from __future__ import annotations

import json
import os

from github_client import GitHubClient
import runtime_verification_watchdog as base_watchdog
from runtime_verification_profile_migration import (
    _write as write_migration_evidence,
    migrate_runtime_profile_if_needed,
)
from target_runtime_profile import build_runtime_probe_registry


def main() -> int:
    gh = GitHubClient()
    migration = migrate_runtime_profile_if_needed(
        gh=gh,
        target_token=os.environ.get(
            "ADE_TARGET_GITHUB_TOKEN",
            "",
        ),
    )
    write_migration_evidence(migration)
    print(
        "Runtime profile migration: "
        + json.dumps(migration, sort_keys=True)
    )
    if migration.get("state") == "FAILED":
        return 1

    base_watchdog.build_runtime_probe_registry = (
        build_runtime_probe_registry
    )
    return base_watchdog.main()


if __name__ == "__main__":
    raise SystemExit(main())
