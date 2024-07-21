import dataclasses
import json
import random
import re
import warnings
from pathlib import Path

import pandas as pd
from web3 import Web3

import utils
from logger import fmt, logger, TelegramHandler


@dataclasses.dataclass
class BotAccount:
    private_key: str
    username: str
    invite_code: str
    proxy: str
    mobile_proxy_changelink: str
    claim_badges: bool = True
    auto_skip: bool = True
    min_sleep_time: float = 1
    max_sleep_time: float = 10
    max_retries: int = 0

    @property
    def hash(self):
        return Web3.keccak(text=self.private_key).hex()

    @property
    def short_private_key(self):
        return f"{self.private_key[:8]}...{self.private_key[-8:]}"


def read_accounts() -> list[BotAccount]:
    warnings.filterwarnings(
        'ignore',
        category=UserWarning,
        module='openpyxl'
    )

    telegram_path = Path(__file__).parent / 'telegram.json'
    if telegram_path.exists():
        with open(telegram_path) as f:
            bot_info = json.load(f)
            required_bot_fields = {'token', 'chat_id', 'log_level'}
            missing_bot_fields = required_bot_fields - set(bot_info.keys())
            if missing_bot_fields:
                logger.error(f'[Account Loader] Missing fields in telegram.json: {", ".join(missing_bot_fields)}')
                return False

            telegram_token = bot_info['token']
            telegram_chat_id = bot_info['chat_id']
            telegram_log_level = bot_info['log_level']

            if telegram_token and telegram_chat_id:
                try:
                    tg_handler = TelegramHandler(telegram_token, telegram_chat_id)
                except Exception as e:
                    logger.error(f'[Account Loader] Failed to initialize Telegram logger handler: {e}')
                    return False
                logger.add(
                    tg_handler.emit,
                    format=fmt,
                    level=telegram_log_level.upper(),
                    filter=lambda record: record['exception'] is None
                )
            elif telegram_token:
                logger.error(f'[Account Loader] Missing chat_id in {telegram_path.name}')
                return False
            elif telegram_chat_id:
                logger.error(f'[Account Loader] Missing token in {telegram_path.name}')
                return False

    yes_values = {'yes', '+', '1'}

    accounts = []

    default_account_values = {}
    for field in dataclasses.fields(BotAccount):
        if field.default != dataclasses.MISSING:
            default_account_values[field.name] = field.default

    acounts_file_path = Path(__file__).parent / 'accounts.xlsx'

    if not acounts_file_path.exists():
        logger.error(f'[Account Loader] File "{acounts_file_path.name}" does not exist')
        return False

    accounts_file = pd.ExcelFile(acounts_file_path)
    sheets = [sheet.lower() for sheet in accounts_file.sheet_names]
    del accounts_file

    dtype = {
        'Private Key': str,
        'Username': str,
        'Invite Code': str,
        'Claim Badges': str,
        'Auto Skip': str,
        'Min Sleep Time': 'float64',
        'Max Sleep Time': 'float64',
        'Max Retries': 'float64',
        'Proxy': str,
        'Mobile Proxy Changelink': str
    }

    accounts_df = pd.read_excel(
        acounts_file_path,
        sheet_name='accounts',
        dtype=dtype
    )
    accounts_df = accounts_df.apply(lambda x: x.str.strip() if x.dtype == object else x)
    missing_account_columns = set(dtype.keys()) - set(accounts_df.columns)
    accounts_df.columns = ['_'.join(column.lower().split(' ')) for column in accounts_df.columns]
    unknown_account_columns = set(accounts_df.columns) - {field.name for field in dataclasses.fields(BotAccount)}

    if unknown_account_columns:
        logger.error(f'[Account Loader] Unknown account columns in "accounts" sheet: {", ".join(unknown_account_columns)}')
        return False

    if missing_account_columns:
        logger.error(f'[Account Loader] Missing account columns in "accounts" sheet: {", ".join(missing_account_columns)}')
        return False

    accounts_df.dropna(subset=['private_key'], inplace=True)
    for column in accounts_df.columns:
        if column in default_account_values:
            accounts_df[column] = accounts_df[column].fillna(
                default_account_values[column]
            )
        else:
            accounts_df[column] = accounts_df[column].fillna(-31294912).replace(-31294912, None)

    for row in accounts_df.itertuples():
        if not re.match(r'^(0x)?[a-fA-F0-9]{64}$', row.private_key) and not row.private_key.lower() in {'random', 'endrandom'}:
            if len(row.private_key) <= 16:
                short_private_key = row.private_key
            else:
                short_private_key = f'{row.private_key[:8]}...{row.private_key[-8:]}'
            logger.error(f'[Account Loader] Invalid private key "{short_private_key}" on row {row.Index + 1} of "accounts" sheet')
            return False

        if row.proxy:
            if re.match(r'(socks5|http)://', row.proxy):
                proxy = {
                    'http': row.proxy,
                    'https': row.proxy
                }
            elif '/' not in row.proxy:
                proxy = {
                    'http': f'http://{row.proxy}',
                    'https': f'http://{row.proxy}'
                }
            else:
                logger.error(f'[Account Loader] Invalid proxy "{row.proxy}"')
                return False
        else:
            proxy = None

        if row.username and row.username.lower() != 'random' and not utils.check_username(row.username):
            logger.error(f'[Account Loader] Invalid username "{row.username}"')
            return False

        if row.invite_code is None:
            invite_code = '37FHD'
        elif row.invite_code in {'-', 'none'}:
            invite_code = None
        else:
            invite_code = row.invite_code.upper()

            if not utils.check_invite_code(invite_code):
                logger.error(f'[Account Loader] Invalid invite code "{invite_code}". Must be 5 uppercase letters or numbers or "-"/"none"')
                return False

        if isinstance(row.claim_badges, bool):
            claim_badges = row.claim_badges
        else:
            claim_badges = row.claim_badges.lower() in yes_values

        if isinstance(row.auto_skip, bool):
            auto_skip = row.auto_skip
        else:
            auto_skip = row.auto_skip.lower() in yes_values

        try:
            account = BotAccount(
                private_key=row.private_key,
                username=row.username,
                invite_code=invite_code,
                claim_badges=claim_badges,
                auto_skip=auto_skip,
                min_sleep_time=row.min_sleep_time,
                max_sleep_time=row.max_sleep_time,
                max_retries=int(row.max_retries),
                proxy=proxy,
                mobile_proxy_changelink=row.mobile_proxy_changelink,
            )
        except AttributeError as e:
            res = re.search("has no attribute '(?P<attribute>.+)'", str(e))
            if res:
                attribute = res.group('attribute')
                logger.error(f'[Account Loader] Missing {attribute} column in "accounts" sheet')
            else:
                logger.error(f'[Account Loader] Failed to load account: {e}')
            return

        accounts.append(account)

    random_indexes = []

    for index, account in enumerate(accounts):
        if account.private_key.lower() == 'random':
            if random_indexes and len(random_indexes[-1]) == 1:
                logger.error(f'[Account Loader] Found not closed random account on line {random_indexes[-1][0] + 2}')
                return False
            random_indexes.append([index])
        elif account.private_key.lower() == 'endrandom':
            if not random_indexes or len(random_indexes[-1]) == 2:
                logger.error(f'[Account Loader] An EndRandom account found that is not preceded by a Random account on line {index + 3}')
                return False
            random_indexes[-1].append(index)

    if random_indexes:
        if len(random_indexes[-1]) != 2:
            logger.error(f'[Account Loader] Found not closed random account on line {random_indexes[-1][0] + 1}')
            return False

        for start_index, end_index in reversed(random_indexes):
            difference = end_index - start_index - 1
            if difference:
                accounts[start_index:end_index + 1] = random.sample(accounts[start_index + 1:end_index], difference)
            else:
                accounts[start_index:end_index + 1] = []

    return accounts
