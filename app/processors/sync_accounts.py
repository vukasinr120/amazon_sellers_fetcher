from config import get_amazon_accounts
from db import inserter
from utils.step_result import StepResult


def process_sync_accounts(logger):
    row_count = 0
    for account in get_amazon_accounts():
        row_count += inserter.upsert_account(account, logger)
    return StepResult(row_count)


def process_sync_marketplaces(logger):
    row_count = 0
    marketplace_results = []
    for account in get_amazon_accounts():
        for marketplace in account.marketplaces:
            try:
                row_count += inserter.upsert_marketplace(account, marketplace, logger)
                marketplace_results.append(
                    {
                        "marketplace_id": marketplace.marketplace_id,
                        "marketplace_name": marketplace.marketplace_name,
                        "step": "sync_marketplaces",
                        "status": "success",
                    }
                )
            except Exception as exc:
                marketplace_results.append(
                    {
                        "marketplace_id": marketplace.marketplace_id,
                        "marketplace_name": marketplace.marketplace_name,
                        "step": "sync_marketplaces",
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                raise
    return StepResult(row_count, marketplace_results)
