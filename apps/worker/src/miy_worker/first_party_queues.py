"""Print the exact consumer queue inventory without starting a worker or Beat."""

import argparse

from miy_worker.runtime import ensure_api_src_on_path

ensure_api_src_on_path()

from miy_api.core.worker_queue_contract import worker_profile_queues  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("platform", "official"), required=True)
    args = parser.parse_args()
    print(",".join(worker_profile_queues(args.profile)))


if __name__ == "__main__":
    main()
