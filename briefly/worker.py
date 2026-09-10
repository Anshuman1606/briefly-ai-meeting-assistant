"""Standalone worker: python -m briefly.worker."""

import logging
import signal

from briefly.service import Service


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = Service()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: service._stop.set())
    service.run_worker()


if __name__ == "__main__":
    main()
