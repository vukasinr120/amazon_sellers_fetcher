import argparse
import logging
import os
from datetime import datetime, timedelta


def setup_logger():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger("amazon_fetcher")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    return parser.parse_args()


def get_date_range():
    args = parse_args()
    if args.start and args.end:
        return args.start, args.end

    env_start = os.getenv("RUN_DATE_START")
    env_end = os.getenv("RUN_DATE_END")
    if env_start and env_end:
        return env_start, env_end

    yesterday = datetime.today() - timedelta(days=1)
    run_date = yesterday.strftime("%Y-%m-%d")
    return run_date, run_date
