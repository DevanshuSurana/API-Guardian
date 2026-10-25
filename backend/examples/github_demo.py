"""Run API Guardian against a real public GitHub migration example.

Start the backend first, then run this script from the backend directory:
    python examples/github_demo.py
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OWNER = "GeneralMills"
REPOSITORY = "pytrends"
CHANGELOG = (
    "urllib3 2.0 removed the deprecated Retry parameter method_whitelist. "
    "Replace Retry(method_whitelist=...) with Retry(allowed_methods=...). "
    "Preserve the configured HTTP methods and retry behavior."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api",
        default="http://127.0.0.1:8000",
        help="API Guardian base URL (default: %(default)s)",
    )
    args = parser.parse_args()

    payload = {
        "owner": OWNER,
        "repo": REPOSITORY,
        "changelog": CHANGELOG,
    }
    request = Request(
        f"{args.api.rstrip('/')}/api/migrations/analyze",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"Analyzing https://github.com/{OWNER}/{REPOSITORY} ...")
    try:
        with urlopen(request, timeout=600) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"API Guardian returned HTTP {error.code}: {detail}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError) as error:
        print(f"Could not reach API Guardian: {error}", file=sys.stderr)
        print("Check that the backend and Ollama are running.", file=sys.stderr)
        return 1

    print(f"Status: {result['status']}")
    print(f"Breaking change: {result['breaking_change']}")
    print(result["summary"])

    target_change = next(
        (
            change
            for change in result["affected_files"]
            if change["file_path"] == "pytrends/request.py"
        ),
        None,
    )
    if target_change is None:
        print("FAIL: API Guardian did not propose a change for pytrends/request.py")
        return 1

    original = target_change["original_code"]
    updated = target_change["updated_code"]
    if "method_whitelist=" not in original:
        print("FAIL: the source no longer contains the expected old API")
        return 1
    if "method_whitelist=" in updated or "allowed_methods=" not in updated:
        print("FAIL: the proposed code does not contain the expected rename")
        return 1

    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{target_change['file_path']}",
        tofile=f"b/{target_change['file_path']} (proposed)",
        n=3,
    )
    print("\nProposed diff:")
    sys.stdout.writelines(diff)
    print("\nPASS: detected and proposed the expected parameter rename.")
    print("This demo only displays the proposal; it does not modify GitHub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
