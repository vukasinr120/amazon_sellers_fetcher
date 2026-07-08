import json
import os
from datetime import datetime

import pyodbc


class AmazonInserter:
    def __init__(self):
        self.table_configs = {
            "accounts": {"table": "amazon_seller.Dim_Amazon_Accounts", "chunk_size": 100},
            "marketplaces": {"table": "amazon_seller.Dim_Amazon_Marketplaces", "chunk_size": 100},
            "raw_objects": {"table": "amazon_seller.tbl_Amazon_Objects_Raw", "chunk_size": 1000},
        }

    def get_connection(self):
        server = os.getenv("SQL_SERVER")
        database = os.getenv("SQL_DATABASE")
        username = os.getenv("SQL_USERNAME")
        password = os.getenv("SQL_PASSWORD")
        driver = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")
        conn_str = f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};UID={username};PWD={password}"
        return pyodbc.connect(conn_str)

    def upsert_account(self, account, logger):
        sql = """
        MERGE amazon_seller.Dim_Amazon_Accounts AS target
        USING (
            SELECT ? AS AccountID, ? AS AccountName, ? AS SellerID
        ) AS source
        ON target.AccountID = source.AccountID
        WHEN MATCHED THEN
            UPDATE SET
                AccountName = source.AccountName,
                SellerID = source.SellerID,
                IsActive = 1,
                UpdatedDateTime = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN
            INSERT (AccountID, AccountName, SellerID, IsActive)
            VALUES (source.AccountID, source.AccountName, source.SellerID, 1);
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (account.account_id, account.account_name, account.seller_id))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Upserted Amazon account %s (%s)", account.account_name, account.account_id)
        return 1

    def upsert_marketplace(self, account, marketplace, logger):
        sql = """
        MERGE amazon_seller.Dim_Amazon_Marketplaces AS target
        USING (
            SELECT
                ? AS AccountID,
                ? AS MarketplaceID,
                ? AS MarketplaceName,
                ? AS CountryCode,
                ? AS CurrencyCode,
                ? AS RegionCode,
                ? AS Endpoint,
                ? AS AwsRegion
        ) AS source
        ON target.AccountID = source.AccountID AND target.MarketplaceID = source.MarketplaceID
        WHEN MATCHED THEN
            UPDATE SET
                MarketplaceName = source.MarketplaceName,
                CountryCode = source.CountryCode,
                CurrencyCode = source.CurrencyCode,
                RegionCode = source.RegionCode,
                Endpoint = source.Endpoint,
                AwsRegion = source.AwsRegion,
                IsActive = 1,
                UpdatedDateTime = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN
            INSERT (AccountID, MarketplaceID, MarketplaceName, CountryCode, CurrencyCode, RegionCode, Endpoint, AwsRegion, IsActive)
            VALUES (source.AccountID, source.MarketplaceID, source.MarketplaceName, source.CountryCode, source.CurrencyCode, source.RegionCode, source.Endpoint, source.AwsRegion, 1);
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            sql,
            (
                account.account_id,
                marketplace.marketplace_id,
                marketplace.marketplace_name,
                marketplace.country_code,
                marketplace.currency_code,
                marketplace.region,
                marketplace.endpoint,
                marketplace.aws_region,
            ),
        )
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Upserted Amazon marketplace %s for account %s", marketplace.marketplace_id, account.account_id)
        return 1

    def delete_raw_range(self, account_id, marketplace_id, object_type, start_date, end_date, logger):
        table_name = self.table_configs["raw_objects"]["table"]
        sql = f"""
        DELETE FROM {table_name}
        WHERE AccountID = ?
          AND ISNULL(MarketplaceID, '') = ISNULL(?, '')
          AND ObjectType = ?
          AND CAST(SourceUpdatedAt AS DATE) >= ?
          AND CAST(SourceUpdatedAt AS DATE) <= ?
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (account_id, marketplace_id, object_type, start_date, end_date))
        deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()
        if deleted > 0:
            logger.info(
                "Deleted %s existing raw %s rows for account %s marketplace %s",
                deleted,
                object_type,
                account_id,
                marketplace_id,
            )
        return deleted

    def insert_raw_objects(self, rows, logger):
        if not rows:
            return 0

        table_name = self.table_configs["raw_objects"]["table"]
        chunk_size = self.table_configs["raw_objects"]["chunk_size"]
        sql = f"""
        INSERT INTO {table_name} (
            AccountID,
            MarketplaceID,
            ObjectType,
            AmazonObjectID,
            SourceCreatedAt,
            SourceUpdatedAt,
            PayloadJson,
            IngestedAt,
            BatchID
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        total = 0
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.fast_executemany = True

        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            values = [
                (
                    row["AccountID"],
                    row.get("MarketplaceID"),
                    row["ObjectType"],
                    row["AmazonObjectID"],
                    row.get("SourceCreatedAt"),
                    row.get("SourceUpdatedAt"),
                    json.dumps(row["Payload"], separators=(",", ":"), default=str),
                    row["IngestedAt"],
                    row["BatchID"],
                )
                for row in chunk
            ]
            cursor.executemany(sql, values)
            total += len(values)
            logger.info("Inserted %s/%s raw Amazon rows", total, len(rows))

        conn.commit()
        cursor.close()
        conn.close()
        return total

    def build_reporting(self, account_id, start_date, end_date, logger):
        sql = """
        EXEC amazon_seller.p_build_reporting
            @AccountID = ?,
            @StartDate = ?,
            @EndDate = ?
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (account_id, start_date, end_date))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Built Amazon reporting tables for account %s (%s to %s)", account_id, start_date, end_date)


def make_batch_id(prefix):
    return f"{prefix}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"


inserter = AmazonInserter()
