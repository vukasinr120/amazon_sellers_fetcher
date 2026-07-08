from datetime import datetime

from processors.build_reporting import process_build_reporting
from processors.ingest_raw import (
    process_ingest_finances,
    process_ingest_inventory,
    process_ingest_listings,
    process_ingest_orders,
    process_ingest_reports,
)
from processors.sync_accounts import process_sync_accounts, process_sync_marketplaces
from utils.alerts import format_summary_message, send_slack_summary


def run_all_steps_with_summary(start_date, end_date, logger, steps_to_run=None):
    job_summary = {
        "start_time": datetime.now(),
        "start_date": start_date,
        "end_date": end_date,
        "steps": [],
        "errors": [],
    }

    def finalize_and_notify():
        job_summary["end_time"] = datetime.now()
        job_summary["duration"] = (job_summary["end_time"] - job_summary["start_time"]).total_seconds()
        send_slack_summary(format_summary_message(job_summary), logger)

    def run_step(name, func, *args):
        if steps_to_run and name not in steps_to_run:
            logger.info("Skipping %s", name)
            return

        logger.info("Starting step: %s", name)
        started = datetime.now()
        result = None
        try:
            result = func(*args)
            duration = (datetime.now() - started).total_seconds()
            row_count = getattr(result, "row_count", None)
            marketplace_results = getattr(result, "marketplace_results", [])
            status = "success" if row_count is None or row_count > 0 else "no_data"
            job_summary["steps"].append(
                {
                    "name": name,
                    "duration": duration,
                    "status": status,
                    "rows": row_count,
                    "marketplace_results": marketplace_results,
                }
            )
            logger.info("Finished %s in %.1fs", name, duration)
        except Exception as exc:
            duration = (datetime.now() - started).total_seconds()
            row_count = getattr(result, "row_count", None)
            marketplace_results = getattr(result, "marketplace_results", [])
            job_summary["steps"].append(
                {
                    "name": name,
                    "duration": duration,
                    "status": "failed",
                    "rows": row_count,
                    "marketplace_results": marketplace_results,
                }
            )
            job_summary["errors"].append(f"{name}: {exc}")
            logger.exception("Error in %s", name)
            raise

    try:
        run_step("sync_accounts", process_sync_accounts, logger)
        run_step("sync_marketplaces", process_sync_marketplaces, logger)
        run_step("ingest_orders", process_ingest_orders, start_date, end_date, logger)
        run_step("ingest_listings", process_ingest_listings, start_date, end_date, logger)
        run_step("ingest_inventory", process_ingest_inventory, start_date, end_date, logger)
        run_step("ingest_finances", process_ingest_finances, start_date, end_date, logger)
        run_step("ingest_reports", process_ingest_reports, start_date, end_date, logger)
        run_step("build_reporting", process_build_reporting, start_date, end_date, logger)
    except Exception:
        finalize_and_notify()
        raise

    finalize_and_notify()

    print(f"\nAMAZON FETCHER SUMMARY ({start_date} to {end_date})")
    print(f"Total duration: {job_summary['duration']:.1f}s\n")
    for step in job_summary["steps"]:
        rows = f" ({step['rows']:,} rows)" if step["rows"] is not None else ""
        print(f"  [{step['status']}] {step['name']} - {step['duration']:.1f}s{rows}")
        for marketplace_result in step.get("marketplace_results", []):
            market_rows = marketplace_result.get("rows")
            rows_text = f" ({market_rows:,} rows)" if market_rows is not None else ""
            print(
                f"    [{marketplace_result['status']}] "
                f"{marketplace_result['marketplace_name']} - {marketplace_result['step']}{rows_text}"
            )

    return job_summary
