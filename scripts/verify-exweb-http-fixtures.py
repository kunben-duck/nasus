"""Reverify original fixture archives without Git, Docker, HTTP or writes to them."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.exweb_http_fixture_probe import encoded, read_original, replay_exweb_http_fixtures, write_original
from apps.api.app.infrastructure.runner.owned_target_environment import _object


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("choose a new output; existing evidence cannot be overwritten")
    result = replay_exweb_http_fixtures(_object(read_original(args.report, 4 * 1024 * 1024)))
    write_original(args.output, encoded(result))
    print("Original fixture bytes and failed outcomes verified; target was not reexecuted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
