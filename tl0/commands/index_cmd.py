"""Manage the SQLite task index."""

import argparse
import sys


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Manage the task index")
    sub = parser.add_subparsers(dest="subcmd")
    sub.add_parser("rebuild", help="Rebuild the index from scratch")
    args = parser.parse_args(argv)

    if args.subcmd == "rebuild":
        from tl0.common import _get_index
        index = _get_index()
        index.rebuild()
        print("Index rebuilt.")
    else:
        parser.print_help()
        sys.exit(1)
