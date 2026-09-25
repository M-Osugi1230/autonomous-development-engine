from __future__ import annotations

import os
import sys

from ade.providers.jules import JulesProvider
from ade.providers.base import ProviderError


def main() -> int:
    owner = os.environ.get("ADE_GITHUB_OWNER", "M-Osugi1230")
    repo = os.environ.get("ADE_GITHUB_REPO", "autonomous-development-engine")

    try:
        provider = JulesProvider()
        source = provider.find_github_source(owner, repo)
    except (ValueError, ProviderError) as exc:
        print(f"Jules smoke test failed: {exc}", file=sys.stderr)
        return 1

    if source is None:
        print(
            f"Jules authenticated, but {owner}/{repo} was not found in connected sources.",
            file=sys.stderr,
        )
        return 2

    source_name = source.get("name", "<unknown>")
    print(f"PASS: Jules authenticated and repository source is visible: {source_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
