"""Find tasks that are ready to be claimed."""

import argparse
import json


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Find claimable tasks")
    parser.add_argument("--tag", action="append", default=[], help="Filter by tag (can repeat)")
    parser.add_argument("--model", default=None, help="Filter by model")
    parser.add_argument("--limit", type=int, default=0, help="Max results (0 = all)")
    args = parser.parse_args(argv)

    from tl0.common import _get_index
    ready = _get_index().find_ready(model=args.model, tags=args.tag or None)

    if args.limit > 0:
        ready = ready[:args.limit]

    print(json.dumps(ready, indent=2))
