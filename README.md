# Amazon Fetcher

Container App job for pulling Amazon Selling Partner API data into the `amazon_seller` schema in the DWH.

The pipeline is account-config driven. Add future Amazon accounts to `AMAZON_ACCOUNTS_JSON`; all tables use `AccountID`, and marketplace-specific tables also use `MarketplaceID`.

## Current first account

- Account: TitanCards
- Auth mode: private SP-API app self-authorization
- Main pattern: one Amazon account, many marketplaces

## Idempotency pattern

- Raw landing rows are deleted and reloaded by `AccountID + MarketplaceID + ObjectType + SourceUpdatedAt date range`.
- Account-level report rows are deleted and reloaded by `AccountID + ObjectType + SourceUpdatedAt date range`.
- Clean/fact/report tables should be rebuilt from raw payloads by `AccountID + business date range`.
- Dimensions are upserted by Amazon native IDs...

## Local run

```bash
cp .env_example .env
# Fill SQL_* and AMAZON_* values.
python app/main.py --start 2026-06-01 --end 2026-06-16
```

Run selected steps:

```bash
RUN_STEPS=sync_accounts,sync_marketplaces,ingest_orders python app/main.py --start 2026-06-01 --end 2026-06-16
```

## Required Amazon configuration

Set `AMAZON_ACCOUNTS_JSON` or rely on the default TitanCards account when the referenced env vars exist.

AWS IAM keys are not required for this fetcher. It uses Login With Amazon (LWA): client ID, client secret, and the seller refresh token.

```json
[
  {
    "account_id": 1,
    "account_name": "TitanCards",
    "seller_id": "A_SELLER_ID",
    "refresh_token_env": "AMAZON_TITANCARDS_REFRESH_TOKEN",
    "lwa_client_id_env": "AMAZON_LWA_CLIENT_ID",
    "lwa_client_secret_env": "AMAZON_LWA_CLIENT_SECRET",
    "marketplaces": ["A1F83G8C2ARO7P", "A1PA6795UKMFR9"]
  }
]
```

Optional report types:

```bash
AMAZON_REPORT_TYPES=GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL,GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE
```

## CI/CD deployment

GitHub Actions builds the Docker image, pushes it to `voonixacr.azurecr.io/amazon-sellers-fetcher`, and creates or updates the Azure Container Apps Job `amazon-sellers-fetcher-daily`.

Default Azure settings:

```text
Resource group: etl-containerapps
Container Apps environment: env-etl-containerapps
Schedule: 0 6 * * * UTC
```

Required GitHub repository secrets:

```text
AZURE_CREDENTIALS
SQL_SERVER
SQL_DATABASE
SQL_USERNAME
SQL_PASSWORD
AMAZON_LWA_CLIENT_ID
AMAZON_LWA_CLIENT_SECRET
AMAZON_TITANCARDS_REFRESH_TOKEN
AMAZON_TITANCARDS_SELLER_ID
```
