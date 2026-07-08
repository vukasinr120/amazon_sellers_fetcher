from config import get_amazon_accounts
from db import inserter
from utils.step_result import StepResult


def process_build_reporting(start_date, end_date, logger):
    for account in get_amazon_accounts():
        inserter.build_reporting(account.account_id, start_date, end_date, logger)
    return StepResult()
