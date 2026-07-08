import os
import sys
import traceback
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except Exception:
    pass

from amazon_fetcher import run_all_steps_with_summary
from utils.utils import get_date_range, setup_logger


if __name__ == "__main__":
    logger = setup_logger()
    try:
        start_date, end_date = get_date_range()
        steps = os.getenv("RUN_STEPS", "")
        steps_to_run = [s.strip() for s in steps.split(",") if s.strip()] if steps else None
        run_all_steps_with_summary(start_date, end_date, logger, steps_to_run)
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
        traceback.print_exc()
        sys.exit(1)
