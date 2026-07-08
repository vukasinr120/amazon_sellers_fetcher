import json
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests


class AmazonApiError(RuntimeError):
    def __init__(self, status_code, response_text):
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(f"Amazon SP-API request failed: {status_code} {response_text}")


class AmazonClient:
    def __init__(self, account, marketplace):
        self.account = account
        self.marketplace = marketplace
        self.endpoint = marketplace.endpoint
        self.aws_region = marketplace.aws_region
        self.access_token = None
        self.access_token_expires_at = 0

    def _get_access_token(self):
        now = time.time()
        if self.access_token and now < self.access_token_expires_at - 300:
            return self.access_token

        response = None
        for attempt in range(1, 7):
            try:
                response = requests.post(
                    "https://api.amazon.com/auth/o2/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self.account.refresh_token,
                        "client_id": self.account.lwa_client_id,
                        "client_secret": self.account.lwa_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                    timeout=30,
                )
                break
            except requests.RequestException:
                if attempt == 6:
                    raise
                time.sleep(min(2**attempt, 60))

        if not response.ok:
            raise RuntimeError(f"Amazon LWA token request failed: {response.status_code} {response.text}")

        body = response.json()
        self.access_token = body["access_token"]
        self.access_token_expires_at = now + int(body.get("expires_in", 3600))
        return self.access_token

    def _headers_and_payload(self, body):
        access_token = self._get_access_token()
        parsed = urlparse(self.endpoint)
        host = parsed.netloc
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        payload = "" if body is None else json.dumps(body, separators=(",", ":"))

        headers = {
            "Content-Type": "application/json",
            "Host": host,
            "User-Agent": "TitanCardsAmazonFetcher/1.0 (Language=Python)",
            "x-amz-access-token": access_token,
            "x-amz-date": amz_date,
        }

        return headers, payload

    def request(self, method, path, params=None, body=None):
        params = params or {}
        headers, payload = self._headers_and_payload(body)
        url = f"{self.endpoint}{path}"

        for attempt in range(1, 7):
            try:
                response = requests.request(
                    method,
                    url,
                    params=params,
                    data=payload if body is not None else None,
                    headers=headers,
                    timeout=120,
                )
            except requests.RequestException:
                if attempt == 6:
                    raise
                time.sleep(min(2**attempt, 60))
                continue

            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(2**attempt, 60))
                continue
            if not response.ok:
                raise AmazonApiError(response.status_code, response.text)
            if not response.text:
                return {}
            return response.json()

        response.raise_for_status()
        return response.json() if response.text else {}

    def paginate(self, method, path, params=None, body=None, token_field="nextToken"):
        next_token = None
        while True:
            page_params = dict(params or {})
            page_body = dict(body or {}) if body is not None else None
            if next_token:
                if page_body is not None:
                    page_body[token_field] = next_token
                else:
                    page_params[token_field] = next_token

            page = self.request(method, path, page_params, page_body)
            yield page

            payload = page.get("payload") if isinstance(page.get("payload"), dict) else page
            next_token = payload.get(token_field) or page.get(token_field)
            if not next_token:
                break

    def get_orders(self, start_date, end_date):
        params = {
            "MarketplaceIds": self.marketplace.marketplace_id,
            "LastUpdatedAfter": f"{start_date}T00:00:00Z",
            "LastUpdatedBefore": f"{end_date}T23:59:59Z",
        }
        for page in self.paginate("GET", "/orders/v0/orders", params=params, token_field="NextToken"):
            yield from page.get("payload", {}).get("Orders", [])

    def get_order_items(self, order_id):
        path = f"/orders/v0/orders/{quote(order_id, safe='')}/orderItems"
        for page in self.paginate("GET", path, token_field="NextToken"):
            yield from page.get("payload", {}).get("OrderItems", [])

    def search_listings(self):
        params = {
            "marketplaceIds": self.marketplace.marketplace_id,
            "includedData": "summaries,attributes,issues,offers,fulfillmentAvailability",
            "pageSize": 20,
        }
        path = f"/listings/2021-08-01/items/{quote(self.account.seller_id, safe='')}"
        for page in self.paginate("GET", path, params=params, token_field="pageToken"):
            yield from page.get("items", [])

    def get_fba_inventory_summaries(self):
        params = {
            "details": "true",
            "granularityType": "Marketplace",
            "granularityId": self.marketplace.marketplace_id,
            "marketplaceIds": self.marketplace.marketplace_id,
        }
        for page in self.paginate("GET", "/fba/inventory/v1/summaries", params=params, token_field="nextToken"):
            yield from page.get("payload", {}).get("inventorySummaries", [])

    def list_finance_transactions(self, start_date, end_date):
        params = {
            "postedAfter": f"{start_date}T00:00:00Z",
            "postedBefore": f"{end_date}T23:59:59Z",
            "marketplaceId": self.marketplace.marketplace_id,
        }
        for page in self.paginate("GET", "/finances/2024-06-19/transactions", params=params, token_field="nextToken"):
            payload = page.get("payload") if isinstance(page.get("payload"), dict) else page
            yield from payload.get("transactions", [])

    def create_report(self, report_type, start_date, end_date):
        body = {
            "reportType": report_type,
            "marketplaceIds": [self.marketplace.marketplace_id],
            "dataStartTime": f"{start_date}T00:00:00Z",
            "dataEndTime": f"{end_date}T23:59:59Z",
        }
        return self.request("POST", "/reports/2021-06-30/reports", body=body)
