import argparse
import sys

from .. import __version__, preflight
from . import onboarding


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="turnover")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("setup", help="Set up a new device link")

    return parser


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    args = parser.parse_args(argv)

    preflight.preflight()

    if args.command == "setup":
        onboarding.run_onboarding_wizard()


if __name__ == "__main__":
    main()
