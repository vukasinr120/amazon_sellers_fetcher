import hashlib
from datetime import datetime, timezone

from amazon_client import AmazonApiError, AmazonClient
from config import get_amazon_accounts, get_report_types
from db import inserter, make_batch_id
from utils.step_result import StepResult


def _marketplace_result(marketplace, step, status, row_count=0, error=None):
    result = {
        "marketplace_id": marketplace.marketplace_id,
        "marketplace_name": marketplace.marketplace_name,
        "step": step,
        "status": status,
        "rows": row_count,
    }
    if error:
        result["error"] = error
    return result


def _parse_amazon_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _first_present(node, keys):
    for key in keys:
        value = node.get(key)
        if value:
            return value
    return None


def _object_id(object_type, node):
    candidates = {
        "order": ["AmazonOrderId", "orderId"],
        "order_item": ["OrderItemId", "orderItemId", "SellerSKU", "ASIN"],
        "listing": ["sku", "sellerSku", "SKU"],
        "fba_inventory": ["sellerSku", "SellerSKU", "asin", "ASIN"],
        "finance_transaction": ["transactionId", "transactionIdentifier", "postedDate"],
        "report_request": ["reportId"],
    }
    value = _first_present(node, candidates.get(object_type, []))
    if value is not None:
        return str(value)
    return hashlib.sha256(str(node).encode("utf-8")).hexdigest()


def _raw_rows(account, marketplace, object_type, nodes, batch_id, default_source_updated_at=None):
    ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for node in nodes:
        source_created_at = _first_present(node, ["CreatedBefore", "PurchaseDate", "createdDate", "postedDate"])
        source_updated_at = _first_present(
            node,
            ["LastUpdateDate", "PurchaseDate", "lastUpdatedDate", "postedDate", "createdTime"],
        )
        parsed_source_updated_at = _parse_amazon_datetime(source_updated_at) or default_source_updated_at
        rows.append(
            {
                "AccountID": account.account_id,
                "MarketplaceID": marketplace.marketplace_id if marketplace else None,
                "ObjectType": object_type,
                "AmazonObjectID": _object_id(object_type, node),
                "SourceCreatedAt": _parse_amazon_datetime(source_created_at),
                "SourceUpdatedAt": parsed_source_updated_at or datetime.now(timezone.utc).replace(tzinfo=None),
                "Payload": node,
                "IngestedAt": ingested_at,
                "BatchID": batch_id,
            }
        )
    return rows


def _ingest_marketplace_stream(account, marketplace, object_type, fetcher, start_date, end_date, logger):
    batch_id = make_batch_id(f"{account.account_id}_{marketplace.marketplace_id}_{object_type}")
    default_source_updated_at = _parse_amazon_datetime(f"{end_date}T23:59:59Z")
    logger.info(
        "Fetching Amazon %s for %s / %s (%s to %s)",
        object_type,
        account.account_name,
        marketplace.marketplace_name,
        start_date,
        end_date,
    )
    nodes = list(fetcher())
    rows = _raw_rows(account, marketplace, object_type, nodes, batch_id, default_source_updated_at)
    inserter.delete_raw_range(account.account_id, marketplace.marketplace_id, object_type, start_date, end_date, logger)
    inserted = inserter.insert_raw_objects(rows, logger)
    logger.info(
        "Inserted %s raw Amazon %s rows for %s / %s",
        inserted,
        object_type,
        account.account_name,
        marketplace.marketplace_name,
    )
    return inserted


def process_ingest_orders(start_date, end_date, logger):
    total = 0
    marketplace_results = []
    for account in get_amazon_accounts():
        for marketplace in account.marketplaces:
            marketplace_total = 0
            try:
                client = AmazonClient(account, marketplace)
                orders = list(client.get_orders(start_date, end_date))
                marketplace_total += _ingest_marketplace_stream(
                    account,
                    marketplace,
                    "order",
                    lambda orders=orders: orders,
                    start_date,
                    end_date,
                    logger,
                )

                item_rows = []
                for order in orders:
                    order_id = order.get("AmazonOrderId")
                    if not order_id:
                        continue
                    for item in client.get_order_items(order_id):
                        item["AmazonOrderId"] = order_id
                        item_rows.append(item)

                batch_id = make_batch_id(f"{account.account_id}_{marketplace.marketplace_id}_order_item")
                rows = _raw_rows(
                    account,
                    marketplace,
                    "order_item",
                    item_rows,
                    batch_id,
                    _parse_amazon_datetime(f"{end_date}T23:59:59Z"),
                )
                inserter.delete_raw_range(
                    account.account_id,
                    marketplace.marketplace_id,
                    "order_item",
                    start_date,
                    end_date,
                    logger,
                )
                marketplace_total += inserter.insert_raw_objects(rows, logger)
                total += marketplace_total
                marketplace_results.append(
                    _marketplace_result(marketplace, "ingest_orders", "success", marketplace_total)
                )
            except Exception as exc:
                marketplace_results.append(
                    _marketplace_result(marketplace, "ingest_orders", "failed", marketplace_total, str(exc))
                )
                raise
    return StepResult(total, marketplace_results)


def process_ingest_listings(start_date, end_date, logger):
    total = 0
    marketplace_results = []
    for account in get_amazon_accounts():
        for marketplace in account.marketplaces:
            client = AmazonClient(account, marketplace)
            try:
                row_count = _ingest_marketplace_stream(
                    account,
                    marketplace,
                    "listing",
                    client.search_listings,
                    start_date,
                    end_date,
                    logger,
                )
                total += row_count
                marketplace_results.append(_marketplace_result(marketplace, "ingest_listings", "success", row_count))
            except AmazonApiError as exc:
                if exc.status_code == 403:
                    logger.warning(
                        "Skipping Amazon listings for %s / %s: SP-API returned 403. "
                        "The app may not have listing access for this marketplace.",
                        account.account_name,
                        marketplace.marketplace_name,
                    )
                    marketplace_results.append(
                        _marketplace_result(marketplace, "ingest_listings", "failed", 0, str(exc))
                    )
                    continue
                marketplace_results.append(
                    _marketplace_result(marketplace, "ingest_listings", "failed", 0, str(exc))
                )
                raise
    return StepResult(total, marketplace_results)


def process_ingest_inventory(start_date, end_date, logger):
    total = 0
    marketplace_results = []
    for account in get_amazon_accounts():
        for marketplace in account.marketplaces:
            client = AmazonClient(account, marketplace)
            try:
                row_count = _ingest_marketplace_stream(
                    account,
                    marketplace,
                    "fba_inventory",
                    client.get_fba_inventory_summaries,
                    start_date,
                    end_date,
                    logger,
                )
                total += row_count
                marketplace_results.append(_marketplace_result(marketplace, "ingest_inventory", "success", row_count))
            except AmazonApiError as exc:
                if exc.status_code == 403:
                    logger.warning(
                        "Skipping Amazon FBA inventory for %s / %s: SP-API returned 403. "
                        "The app may not have inventory access for this marketplace.",
                        account.account_name,
                        marketplace.marketplace_name,
                    )
                    marketplace_results.append(
                        _marketplace_result(marketplace, "ingest_inventory", "failed", 0, str(exc))
                    )
                    continue
                marketplace_results.append(
                    _marketplace_result(marketplace, "ingest_inventory", "failed", 0, str(exc))
                )
                raise
    return StepResult(total, marketplace_results)


def process_ingest_finances(start_date, end_date, logger):
    total = 0
    marketplace_results = []
    for account in get_amazon_accounts():
        for marketplace in account.marketplaces:
            client = AmazonClient(account, marketplace)
            try:
                row_count = _ingest_marketplace_stream(
                    account,
                    marketplace,
                    "finance_transaction",
                    lambda client=client: client.list_finance_transactions(start_date, end_date),
                    start_date,
                    end_date,
                    logger,
                )
                total += row_count
                marketplace_results.append(_marketplace_result(marketplace, "ingest_finances", "success", row_count))
            except AmazonApiError as exc:
                if exc.status_code == 403:
                    logger.warning(
                        "Skipping Amazon finances for %s / %s: SP-API returned 403. "
                        "The app likely needs the Finance and Accounting role.",
                        account.account_name,
                        marketplace.marketplace_name,
                    )
                    marketplace_results.append(
                        _marketplace_result(marketplace, "ingest_finances", "failed", 0, str(exc))
                    )
                    continue
                marketplace_results.append(
                    _marketplace_result(marketplace, "ingest_finances", "failed", 0, str(exc))
                )
                raise
    return StepResult(total, marketplace_results)


def process_ingest_reports(start_date, end_date, logger):
    report_types = get_report_types()
    if not report_types:
        logger.info("AMAZON_REPORT_TYPES not set; skipping Amazon report requests.")
        return StepResult(0)

    total = 0
    marketplace_results = []
    for account in get_amazon_accounts():
        for marketplace in account.marketplaces:
            try:
                client = AmazonClient(account, marketplace)
                requests = []
                for report_type in report_types:
                    response = client.create_report(report_type, start_date, end_date)
                    response["reportType"] = report_type
                    requests.append(response)
                batch_id = make_batch_id(f"{account.account_id}_{marketplace.marketplace_id}_report_request")
                rows = _raw_rows(
                    account,
                    marketplace,
                    "report_request",
                    requests,
                    batch_id,
                    _parse_amazon_datetime(f"{end_date}T23:59:59Z"),
                )
                inserter.delete_raw_range(
                    account.account_id,
                    marketplace.marketplace_id,
                    "report_request",
                    start_date,
                    end_date,
                    logger,
                )
                row_count = inserter.insert_raw_objects(rows, logger)
                total += row_count
                marketplace_results.append(_marketplace_result(marketplace, "ingest_reports", "success", row_count))
            except AmazonApiError as exc:
                if exc.status_code == 403:
                    logger.warning(
                        "Skipping Amazon reports for %s / %s: SP-API returned 403.",
                        account.account_name,
                        marketplace.marketplace_name,
                    )
                    marketplace_results.append(
                        _marketplace_result(marketplace, "ingest_reports", "failed", 0, str(exc))
                    )
                    continue
                marketplace_results.append(_marketplace_result(marketplace, "ingest_reports", "failed", 0, str(exc)))
                raise
    return StepResult(total, marketplace_results)
