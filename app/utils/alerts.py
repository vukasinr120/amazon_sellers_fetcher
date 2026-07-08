import os

import requests


def _marketplace_results(job_summary):
    results = []
    for step in job_summary["steps"]:
        results.extend(step.get("marketplace_results", []))
    return results


def _has_marketplace_failures(job_summary):
    return any(result.get("status") == "failed" for result in _marketplace_results(job_summary))


def _format_country_summary(job_summary):
    results = _marketplace_results(job_summary)
    if not results:
        return []

    by_marketplace = {}
    for result in results:
        name = result.get("marketplace_name") or result.get("marketplace_id") or "Unknown"
        by_marketplace.setdefault(name, []).append(result)

    lines = ["", ":earth_africa: Marketplaces:"]
    for name in sorted(by_marketplace):
        market_results = by_marketplace[name]
        passed = sum(1 for result in market_results if result.get("status") != "failed")
        failed = sum(1 for result in market_results if result.get("status") == "failed")
        emoji = ":white_check_mark:" if failed == 0 else ":warning:"
        if failed == 0:
            detail = "all passed"
        else:
            detail = f"{passed} passed {failed} failed"
        lines.append(f"{emoji} {name} - {detail}")

    failed_lines = []
    for name in sorted(by_marketplace):
        market_results = by_marketplace[name]
        failed_steps = [result.get("step", "unknown_step") for result in market_results if result.get("status") == "failed"]
        if not failed_steps:
            continue
        if len(failed_steps) == len(market_results):
            failed_lines.append(f"{name} - All failed")
        else:
            failed_lines.append(f"{name} - {', '.join(failed_steps)}")

    if failed_lines:
        lines.append("")
        lines.append(":warning: Failed Details:")
        lines.extend(failed_lines)

    return lines


def format_summary_message(job_summary):
    date_text = job_summary["start_date"]
    if job_summary["start_date"] != job_summary["end_date"]:
        date_text = f"{job_summary['start_date']} to {job_summary['end_date']}"

    lines = [
        ":dart: Amazon SP-API Import Summary - TITAN CARDS",
        f":date: Date: {date_text}",
        f":stopwatch: Duration: {job_summary['duration']:.1f}s",
        "",
        ":bricks: Steps:",
    ]

    for step in job_summary["steps"]:
        emoji = ":x:" if step["status"] == "failed" else ":white_check_mark:"
        row_text = f"{step['rows']:,} rows - " if step.get("rows") is not None else ""
        lines.append(f"{emoji} {step['name']} - {row_text}{step['duration']:.1f}s")

    lines.extend(_format_country_summary(job_summary))

    has_marketplace_failures = _has_marketplace_failures(job_summary)

    if job_summary["errors"]:
        lines.append("")
        lines.append(":warning: Errors:")
        for error in job_summary["errors"]:
            lines.append(f"- {error}")
    elif has_marketplace_failures:
        lines.append("")
        lines.append(":warning: Completed with marketplace-level failures.")
    else:
        lines.append("")
        lines.append(":tada: All steps completed successfully.")

    return "\n".join(lines)


def send_slack_summary(summary_text, logger):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.info("SLACK_WEBHOOK_URL not set; skipping Slack summary.")
        return

    try:
        response = requests.post(webhook_url, json={"text": summary_text}, timeout=15)
        response.raise_for_status()
        logger.info("Slack summary sent.")
    except Exception as exc:
        logger.error("Failed to send Slack summary: %s", exc)
