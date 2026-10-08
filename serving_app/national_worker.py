"""Persistent nationwide worker, isolated from Seoul and disabled source guesses."""
import os
import signal
import time
import sys
from serving_app.worker_runtime import run_isolated,has_queued_jobs
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
        if os.getenv('GROUNDWATCH_NATIONAL_SIMULATION_ENABLED','true').lower() in ('true','1','yes'):
            from serving_app.national_simulation import bootstrap as seed_simulation
            from serving_app.national_service import kst_today
            from datetime import timedelta
            seed_simulation(service, 'data', kst_today()-timedelta(days=1),
                int(os.getenv('GROUNDWATCH_SIMULATION_TRAIN_EPOCHS','5')))
        if bootstrap_enabled:
            from scripts.bootstrap_national_models import bootstrap
            bootstrap(service, 'data/national_experimental_joined.json',
                      int(os.getenv('GROUNDWATCH_EXPERIMENTAL_TRAIN_EPOCHS','30')))
    seed_experiments()
    last_schedule = 0.
    from serving_app.national_service import kst_today
    last_simulation_day = kst_today()
    base=[sys.executable,'-m','serving_app.worker_runtime','--state-root',str(service.root.parent),'--action']
    while not stopping:
        if kst_today() != last_simulation_day:
            seed_experiments()
            last_simulation_day = kst_today()
        if automatic and time.monotonic()-last_schedule >= 30:
            run_isolated(base+['national-schedule'],store=service.store,stop_requested=lambda:stopping)
            last_schedule = time.monotonic()
        if not stopping and has_queued_jobs(service.store):
            run_isolated(base+['national-job'],store=service.store,stop_requested=lambda:stopping)
            if not stopping:seed_experiments()
        else:
            time.sleep(.5)


if __name__ == '__main__':
    main()
