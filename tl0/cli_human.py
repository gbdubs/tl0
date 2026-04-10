"""tl0h — DEPRECATED. Use tl1 instead."""

import sys


def main():
    print(
        "Error: tl0 has been deprecated. Please use tl1 instead.\n"
        "\n"
        "  tl0h has been replaced by tl1h.\n"
        "  For migration details, see the tl1 documentation.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
