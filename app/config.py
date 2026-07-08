import json
import os
from dataclasses import dataclass


MARKETPLACE_METADATA = {
    "A1F83G8C2ARO7P": {"name": "United Kingdom", "country_code": "UK", "currency_code": "GBP", "region": "EU"},
    "A1PA6795UKMFR9": {"name": "Germany", "country_code": "DE", "currency_code": "EUR", "region": "EU"},
    "A13V1IB3VIYZZH": {"name": "France", "country_code": "FR", "currency_code": "EUR", "region": "EU"},
    "APJ6JRA9NG5V4": {"name": "Italy", "country_code": "IT", "currency_code": "EUR", "region": "EU"},
    "A1RKKUPIHCS9HS": {"name": "Spain", "country_code": "ES", "currency_code": "EUR", "region": "EU"},
    "A1805IZSGTT6HS": {"name": "Netherlands", "country_code": "NL", "currency_code": "EUR", "region": "EU"},
    "AMEN7PMS3EDWL": {"name": "Belgium", "country_code": "BE", "currency_code": "EUR", "region": "EU"},
    "A28R8C7NBKEWEA": {"name": "Ireland", "country_code": "IE", "currency_code": "EUR", "region": "EU"},
    "A1C3SOZRARQ6R3": {"name": "Poland", "country_code": "PL", "currency_code": "PLN", "region": "EU"},
    "A2NODRKZP88ZB9": {"name": "Sweden", "country_code": "SE", "currency_code": "SEK", "region": "EU"},
    "A17E79C6D8DWNP": {"name": "Saudi Arabia", "country_code": "SA", "currency_code": "SAR", "region": "EU"},
    "A33AVAJ2PDY3EV": {"name": "Turkey", "country_code": "TR", "currency_code": "TRY", "region": "EU"},
    "A2VIGQ35RCS4UG": {"name": "United Arab Emirates", "country_code": "AE", "currency_code": "AED", "region": "EU"},
    "A39IBJ37TRP1C6": {"name": "Australia", "country_code": "AU", "currency_code": "AUD", "region": "FE"},
}

REGION_ENDPOINTS = {
    "NA": {"endpoint": "https://sellingpartnerapi-na.amazon.com", "aws_region": "us-east-1"},
    "EU": {"endpoint": "https://sellingpartnerapi-eu.amazon.com", "aws_region": "eu-west-1"},
    "FE": {"endpoint": "https://sellingpartnerapi-fe.amazon.com", "aws_region": "us-west-2"},
}


@dataclass(frozen=True)
class AmazonMarketplaceConfig:
    marketplace_id: str
    marketplace_name: str
    country_code: str | None
    currency_code: str | None
    region: str
    endpoint: str
    aws_region: str


@dataclass(frozen=True)
class AmazonAccountConfig:
    account_id: int
    account_name: str
    seller_id: str
    refresh_token: str
    lwa_client_id: str
    lwa_client_secret: str
    marketplaces: tuple[AmazonMarketplaceConfig, ...]


def _default_account_configs():
    required = [
        "AMAZON_TITANCARDS_REFRESH_TOKEN",
        "AMAZON_TITANCARDS_SELLER_ID",
        "AMAZON_LWA_CLIENT_ID",
        "AMAZON_LWA_CLIENT_SECRET",
    ]
    if not all(os.getenv(name) for name in required):
        return []

    return [
        {
            "account_id": 1,
            "account_name": "TitanCards",
            "seller_id_env": "AMAZON_TITANCARDS_SELLER_ID",
            "refresh_token_env": "AMAZON_TITANCARDS_REFRESH_TOKEN",
            "lwa_client_id_env": "AMAZON_LWA_CLIENT_ID",
            "lwa_client_secret_env": "AMAZON_LWA_CLIENT_SECRET",
            "marketplaces": list(MARKETPLACE_METADATA.keys()),
        }
    ]


def _env_or_value(config, value_key, env_key):
    value = config.get(value_key)
    if value:
        return value
    env_name = config.get(env_key)
    return os.getenv(env_name or "")


def _marketplace_config(marketplace_id):
    metadata = MARKETPLACE_METADATA.get(marketplace_id, {})
    region = metadata.get("region") or "EU"
    region_config = REGION_ENDPOINTS[region]
    return AmazonMarketplaceConfig(
        marketplace_id=marketplace_id,
        marketplace_name=metadata.get("name") or marketplace_id,
        country_code=metadata.get("country_code"),
        currency_code=metadata.get("currency_code"),
        region=region,
        endpoint=region_config["endpoint"],
        aws_region=region_config["aws_region"],
    )


def get_amazon_accounts():
    raw = os.getenv("AMAZON_ACCOUNTS_JSON")
    configs = json.loads(raw) if raw else _default_account_configs()
    accounts = []

    for config in configs:
        seller_id = _env_or_value(config, "seller_id", "seller_id_env")
        refresh_token = _env_or_value(config, "refresh_token", "refresh_token_env")
        lwa_client_id = _env_or_value(config, "lwa_client_id", "lwa_client_id_env")
        lwa_client_secret = _env_or_value(config, "lwa_client_secret", "lwa_client_secret_env")

        missing = [
            name
            for name, value in {
                "seller_id": seller_id,
                "refresh_token": refresh_token,
                "lwa_client_id": lwa_client_id,
                "lwa_client_secret": lwa_client_secret,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"Missing Amazon credentials for {config.get('account_name')}: {', '.join(missing)}")

        marketplaces = tuple(_marketplace_config(marketplace_id) for marketplace_id in config.get("marketplaces", []))
        if not marketplaces:
            raise ValueError(f"No Amazon marketplaces configured for {config.get('account_name')}")

        accounts.append(
            AmazonAccountConfig(
                account_id=int(config["account_id"]),
                account_name=config["account_name"],
                seller_id=seller_id,
                refresh_token=refresh_token,
                lwa_client_id=lwa_client_id,
                lwa_client_secret=lwa_client_secret,
                marketplaces=marketplaces,
            )
        )

    if not accounts:
        raise ValueError("No Amazon accounts configured. Set AMAZON_ACCOUNTS_JSON or TitanCards Amazon env vars.")

    return accounts


def get_report_types():
    raw = os.getenv("AMAZON_REPORT_TYPES", "")
    return [report_type.strip() for report_type in raw.split(",") if report_type.strip()]
