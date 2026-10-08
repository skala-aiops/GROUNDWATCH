"""Persistent nationwide worker, isolated from Seoul and disabled source guesses."""
import os
import signal
import time
from serving_app.national_service import NationalService


def main():
    service = NationalService(os.getenv('GROUNDWATCH_STATE_DIR', 'runtime/groundwatch'))
    service.store.recover()
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    automatic = os.getenv('GROUNDWATCH_NATIONAL_SCHEDULER_ENABLED', 'false').lower() in ('true','1','yes')
    bootstrap_enabled = os.getenv('GROUNDWATCH_EXPERIMENTAL_MODELS_ENABLED', 'false').lower() in ('true','1','yes')
    def seed_experiments():
        if bootstrap_enabled:
            from scripts.bootstrap_national_models import bootstrap
            bootstrap(service, 'data/national_experimental_joined.json',
                      int(os.getenv('GROUNDWATCH_EXPERIMENTAL_TRAIN_EPOCHS','30')))
    seed_experiments()
    last_schedule = 0.
    while not stopping:
        if automatic and time.monotonic()-last_schedule >= 30:
            service.schedule_once()
            last_schedule = time.monotonic()
        if service.execute_one():
            seed_experiments()
        else:
            time.sleep(.5)


if __name__ == '__main__':
    main()
