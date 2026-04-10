"""tl0m — DEPRECATED. Use tl1 instead."""

import sys


def main():
    print(
        "Error: tl0 has been deprecated. Please use tl1 instead.\n"
        "\n"
        "  tl0m has been replaced by tl1m.\n"
        "  For migration details, see the tl1 documentation.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
