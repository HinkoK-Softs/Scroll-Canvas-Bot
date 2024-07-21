import json
import re
import time
from pathlib import Path

import eth_abi
import requests
from eth_account import Account
from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes
from pydantic import BaseModel, Field, validator
from web3 import Web3

import accounts_loader
import constants
import enums
import utils
from logger import logger

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'


class ContractTypes(enums.AutoEnum):
    ProfileRegistry = enums.auto()
    ScrollOriginsAttestor = enums.auto()
    ScrollOriginsBadge = enums.auto()
    ScrollOriginsNFT = enums.auto()


CONTRACT_ADRESSES = {
    ContractTypes.ProfileRegistry: {
        enums.NetworkNames.Scroll: '0xB23AF8707c442f59BDfC368612Bd8DbCca8a7a5a'
    },
    ContractTypes.ScrollOriginsAttestor: {
        enums.NetworkNames.Scroll: '0xC47300428b6AD2c7D03BB76D05A176058b47E6B0'
    },
    ContractTypes.ScrollOriginsBadge: {
        enums.NetworkNames.Scroll: '0x2dBce60ebeAafb77e5472308f432F78aC3AE07d9'
    },
    ContractTypes.ScrollOriginsNFT: {
        enums.NetworkNames.Scroll: '0x74670A3998d9d6622E32D0847fF5977c37E0eC91'
    }
}


class MintInfo(BaseModel):
    address: str
    data: str


class Badge(BaseModel):
    name: str
    base_url: str = Field(alias='baseUrl')
    contract_address: str = Field(alias='badgeContract')
    description: str
    mint_info: MintInfo = None

    class Config:
        allow_population_by_field_name = True

    @validator('contract_address')
    def validate_contract_address(cls, v):
        return Web3.to_checksum_address(v)


MINT_FEE = 1000000000000000

CUSTOM_BADGES = [
    Badge(
        name='Ethereum Year',
        base_url='https://canvas.scroll.cat/badge',
        contract_address='0x3dacAd961e5e2de850F5E027c70b56b5Afa5DfeD',
        description="Check out the Ethereum Year Badge! It's like a digital trophy that shows off the year your wallet made its debut on Ethereum. It's a little present from Scroll to celebrate all the cool stuff you've done in the Ethereum ecosystem."
    )
]


def get_eligible_badges(
    web3: Web3,
    address: str,
    proxy: dict[str, str]
) -> list[Badge]:
    logger.info(f'[Scroll Canvas] Fetching eligible badges')

    headers = {
        'User-Agent': USER_AGENT
    }

    badgelist_response = requests.get(
        'https://raw.githubusercontent.com/scroll-tech/canvas-badges/main/scroll.badgelist.json',
        headers=headers,
        timeout=5,
        proxies=proxy
    )

    if not badgelist_response.ok:
        logger.error(f'[Scroll Canvas] Failed to get the badge list: {badgelist_response.status_code} - {badgelist_response.text}')
        return

    badgelist: list[dict] = badgelist_response.json()['badges']

    badgelist: list[Badge] = [Badge(**badge) for badge in badgelist]

    badgelist: list[Badge] = CUSTOM_BADGES + badgelist

    logger.info(f'[Scroll Canvas] Fetched {len(badgelist)} badges, checking eligibility')

    mintable_badges = []

    with open(Path(__file__).parent / 'abi' / 'Badge.json') as file:
        badge_abi = file.read()

    for badge in badgelist:
        badge_contract = web3.eth.contract(
            address=Web3.to_checksum_address(badge.contract_address),
            abi=badge_abi
        )

        if badge_contract.functions.hasBadge(address).call():
            logger.info(f'[Scroll Canvas] {badge.name} badge is already claimed')
            continue

        request_params = {
            'badge': badge.contract_address,
            'recipient': address
        }

        try:
            check_response = requests.get(
                f'{badge.base_url}/check',
                params=request_params,
                headers=headers,
                timeout=5,
                proxies=proxy
            )
        except requests.exceptions.RequestException as e:
            logger.warning(f'[Scroll Canvas] Failed to check eligibility for {badge.name} badge. Usually this is okay')
        else:
            if check_response.ok:
                check_json = check_response.json()

                message = check_json.get('message', '')
                eligible = check_json['eligibility']

                if eligible:
                    logger.success(f'[Scroll Canvas] Account is eligible for {badge.name} badge')

                    try:
                        claim_response = requests.get(
                            f'{badge.base_url}/claim',
                            params=request_params,
                            headers=headers,
                            timeout=5,
                            proxies=proxy
                        )
                    except requests.exceptions.RequestException as e:
                        logger.error(f'[Scroll Canvas] Failed to get claim data for {badge.name} badge')
                    else:
                        claim_json = claim_response.json()

                        claim_tx = claim_json['tx']

                        if claim_response.ok:
                            badge.mint_info = MintInfo(
                                address=Web3.to_checksum_address(claim_tx['to']),
                                data=claim_tx['data']
                            )

                            mintable_badges.append(badge)
                        else:
                            logger.error(f'[Scroll Canvas] Failed to get claim data for {badge.name} badge: {claim_response.status_code} - {claim_response.text}')
                else:
                    logger.info(f'[Scroll Canvas] Account is not eligible for {badge.name} badge: {message}')
                    logger.info(f'[Scroll Canvas] Requirement: {badge.description}')

    return mintable_badges


def register_and_claim(
    private_key: str,
    network_name: enums.NetworkNames,
    username: str,
    invite_code: str,
    claim_badges: bool,
    proxy: dict[str, str]
):
    headers = {
        'User-Agent': USER_AGENT
    }

    network = constants.NETWORKS[network_name]

    web3 = Web3(
        Web3.HTTPProvider(
            network.rpc_url,
            request_kwargs={
                'proxies': proxy
            }
        )
    )

    account: LocalAccount = Account.from_key(private_key)

    with open(Path(__file__).parent / 'abi' / 'ProfileRegistry.json') as file:
        profile_registry_abi = file.read()

    profile_registry_contract = web3.eth.contract(
        address=CONTRACT_ADRESSES[ContractTypes.ProfileRegistry][network_name],
        abi=profile_registry_abi
    )

    profile_address = profile_registry_contract.functions.getProfile(
        account.address
    ).call()

    if profile_registry_contract.functions.isProfileMinted(profile_address).call():
        logger.info(f'[Scroll Canvas] Profile is already minted for {account.address}')
    else:
        logger.info(f'[Scroll Canvas] Minting profile for {account.address}')

        if not username or username.lower() == 'random':
            logger.info(f'[Scroll Canvas] Generating random username')

            while True:
                user_response = requests.get(
                    'https://randomuser.me/api/',
                    headers=headers,
                    timeout=5,
                    proxies=proxy
                )

                if user_response.ok:
                    user_json = user_response.json()

                    username = user_json['results'][0]['login']['username']

                    if utils.check_username(username) and not profile_registry_contract.functions.isUsernameUsed(username).call():
                        break
                else:
                    logger.error(f'[Scroll Canvas] Failed to get random username: {user_response.status_code} - {user_response.text}')

                time.sleep(1)

            logger.info(f'[Scroll Canvas] Generated username: {username}')
        elif not utils.check_username(username):
            logger.error(f'[Scroll Canvas] Invalid username: {username}. Must be 4-15 characters long and contain only letters, numbers, and underscores')
            return enums.TransactionStatus.FAILED
        elif profile_registry_contract.functions.isUsernameUsed(username).call():
            logger.error(f'[Scroll Canvas] Username {username} is already taken')
            return enums.TransactionStatus.FAILED

        if invite_code:
            invite_code = invite_code.upper()

            if not utils.check_invite_code(invite_code):
                logger.error(f'[Scroll Canvas] Invalid invite code: {invite_code}. Must be 5 uppercase letters or numbers')
                return enums.TransactionStatus.FAILED

            code_check_response = requests.get(
                f'https://canvas.scroll.cat/code/{invite_code}/active',
                headers=headers,
                proxies=proxy
            )

            if not code_check_response.ok:
                logger.error(f'[Scroll Canvas] Invalid invite code: {invite_code}')
                return enums.TransactionStatus.FAILED

            code_check_json = code_check_response.json()

            if not code_check_json['active']:
                logger.error(f'[Scroll Canvas] Invite code {invite_code} is not active')
                return enums.TransactionStatus.FAILED

            referral_response = requests.get(
                url=f'https://canvas.scroll.cat/code/{invite_code}/sig/{account.address}',
                headers=headers,
                proxies=proxy
            )

            if not referral_response.ok:
                logger.error(f'[Scroll Canvas] Failed to get mint signature: {referral_response.status_code} - {referral_response.text}')
                return enums.TransactionStatus.FAILED

            referral_json = referral_response.json()

            referral_signature = HexBytes(referral_json['signature'])

            mint_fee = MINT_FEE // 2
        else:
            referral_signature = b''
            mint_fee = MINT_FEE

        gas_price = utils.suggest_gas_fees(
            network_name=network_name,
            proxy=proxy
        )

        if not gas_price:
            return enums.TransactionStatus.FAILED

        txn = profile_registry_contract.functions.mint(
            username,
            referral_signature
        ).build_transaction(
            {
                'chainId': network.chain_id,
                'nonce': web3.eth.get_transaction_count(account.address),
                'from': account.address,
                'value': mint_fee,
                'gas': 0,
                **gas_price
            }
        )

        try:
            txn['gas'] = utils.estimate_gas(web3, txn)
        except Exception as e:
            if 'insufficient funds' in str(e):
                logger.critical(f'[Scroll Canvas] Insufficient balance to mint profile')
                return enums.TransactionStatus.INSUFFICIENT_BALANCE
            logger.error(f'[Scroll Canvas] Error while estimating gas: {e}')
            return enums.TransactionStatus.FAILED

        signed_txn = account.sign_transaction(txn)

        txn_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)

        logger.info(f'[Scroll Canvas] Transaction: {network.txn_explorer_url}{txn_hash.hex()}')

        receipt = utils.wait_for_transaction_receipt(
            web3=web3.eth,
            txn_hash=txn_hash,
            logging_prefix='Scroll Canvas'
        )

        if receipt and receipt['status'] == 1:
            logger.success(f'[Scroll Canvas] Successfully minted profile for {account.address}')
        else:
            logger.error(f'[Scroll Canvas] Failed to mint profile for {account.address}')
            return enums.TransactionStatus.FAILED

        utils.random_sleep()

    if not claim_badges:
        return enums.TransactionStatus.SUCCESS

    eligible_badges = get_eligible_badges(
        web3=web3,
        address=account.address,
        proxy=proxy
    )

    if eligible_badges is None:
        return enums.TransactionStatus.FAILED

    if eligible_badges:
        logger.info(f'[Scroll Canvas] Claiming {len(eligible_badges)} badges')

        for badge in eligible_badges:
            gas_price = utils.suggest_gas_fees(
                network_name=network_name,
                proxy=proxy
            )

            if not gas_price:
                return enums.TransactionStatus.FAILED

            txn = {
                'chainId': network.chain_id,
                'nonce': web3.eth.get_transaction_count(account.address),
                'from': account.address,
                'to': badge.mint_info.address,
                'data': badge.mint_info.data,
                'value': 0,
                'gas': 0,
                **gas_price
            }

            try:
                txn['gas'] = utils.estimate_gas(web3, txn)
            except Exception as e:
                if 'insufficient funds' in str(e):
                    logger.critical(f'[Scroll Canvas] Insufficient balance to claim {badge.name} badge')
                    return enums.TransactionStatus.INSUFFICIENT_BALANCE
                logger.error(f'[Scroll Canvas] Error while estimating gas: {e}')
                return enums.TransactionStatus.FAILED

            signed_txn = account.sign_transaction(txn)

            txn_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)

            logger.info(f'[Scroll Canvas] Transaction: {network.txn_explorer_url}{txn_hash.hex()}')

            receipt = utils.wait_for_transaction_receipt(
                web3=web3.eth,
                txn_hash=txn_hash,
                logging_prefix='Scroll Canvas'
            )

            if receipt and receipt['status'] == 1:
                logger.success(f'[Scroll Canvas] Successfully claimed {badge.name} badge')
            else:
                logger.error(f'[Scroll Canvas] Failed to claim {badge.name} badge')
                return enums.TransactionStatus.FAILED

            utils.random_sleep()
    else:
        logger.info(f'[Scroll Canvas] No badges to claim were found')

    logger.info(f'[Scroll Canvas] Checking eligibility for Scroll Origins NFT badge')

    with open(Path(__file__).parent / 'abi' / 'ScrollBadgeTokenOwner.json') as file:
        scroll_origins_badge_abi = file.read()

    scroll_badge_contract = web3.eth.contract(
        address=CONTRACT_ADRESSES[ContractTypes.ScrollOriginsBadge][network_name],
        abi=scroll_origins_badge_abi
    )

    if scroll_badge_contract.functions.hasBadge(account.address).call():
        logger.info(f'[Scroll Canvas] Scroll Origins NFT badge is already claimed')
    else:
        with open(Path(__file__).parent / 'abi' / 'ScrollOriginsNFT.json') as file:
            scroll_origins_nft_abi = file.read()

        scroll_origins_nft_contract = web3.eth.contract(
            address=CONTRACT_ADRESSES[ContractTypes.ScrollOriginsNFT][network_name],
            abi=scroll_origins_nft_abi
        )

        if scroll_origins_nft_contract.functions.minted(account.address).call():
            logger.success(f'[Scroll Canvas] Account is eligible for Scroll Origins NFT badge, claiming')

            nft_id = scroll_origins_nft_contract.functions.tokenOfOwnerByIndex(
                account.address,
                0
            ).call()

            with open(Path(__file__).parent / 'abi' / 'EAS.json') as file:
                attestor_abi = file.read()

            attestor_contract = web3.eth.contract(
                address=CONTRACT_ADRESSES[ContractTypes.ScrollOriginsAttestor][network_name],
                abi=attestor_abi
            )

            data = eth_abi.encode(
                ['address', 'uint256', 'uint256', 'address', 'uint256'],
                [
                    scroll_badge_contract.address,
                    0x40,
                    0x40,
                    scroll_origins_nft_contract.address,
                    nft_id
                ]
            )

            gas_price = utils.suggest_gas_fees(
                network_name=network_name,
                proxy=proxy
            )

            if not gas_price:
                return enums.TransactionStatus.FAILED

            txn = attestor_contract.functions.attest(
                (
                    HexBytes('0xd57de4f41c3d3cc855eadef68f98c0d4edd22d57161d96b7c06d2f4336cc3b49'),
                    (
                        account.address,
                        0,
                        False,
                        HexBytes(f'0x{"00" * 32}'),
                        data,
                        0
                    )
                )
            ).build_transaction(
                {
                    'chainId': network.chain_id,
                    'nonce': web3.eth.get_transaction_count(account.address),
                    'from': account.address,
                    'value': 0,
                    'gas': 0,
                    **gas_price
                }
            )

            try:
                txn['gas'] = utils.estimate_gas(web3, txn)
            except Exception as e:
                if 'insufficient funds' in str(e):
                    logger.critical(f'[Scroll Canvas] Insufficient balance to claim Scroll Origins NFT badge')
                    return enums.TransactionStatus.INSUFFICIENT_BALANCE
                logger.error(f'[Scroll Canvas] Error while estimating gas: {e}')
                return enums.TransactionStatus.FAILED

            signed_txn = account.sign_transaction(txn)

            txn_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)

            logger.info(f'[Scroll Canvas] Transaction: {network.txn_explorer_url}{txn_hash.hex()}')

            receipt = utils.wait_for_transaction_receipt(
                web3=web3.eth,
                txn_hash=txn_hash,
                logging_prefix='Scroll Canvas'
            )

            if receipt and receipt['status'] == 1:
                logger.success(f'[Scroll Canvas] Successfully claimed Scroll Origins NFT badge')
            else:
                logger.error(f'[Scroll Canvas] Failed to claim Scroll Origins NFT badge')
                return enums.TransactionStatus.FAILED
        else:
            logger.info(f'[Scroll Canvas] Account is not eligible for Scroll Origins NFT badge')

    return enums.TransactionStatus.SUCCESS


def run_accounts(bot_accounts: list[accounts_loader.BotAccount]):
    if not bot_accounts:
        return

    accounts_hashes = [bot_account.hash for bot_account in bot_accounts]

    if Path('last_state.json').exists():
        with open('last_state.json', 'r') as file:
            last_state = json.load(file)

        order = last_state.get('order', [])

        if sorted(order) == sorted(accounts_hashes):
            last_bot_index = order.index(last_state['account_hash'])
            last_bot_account = next(
                filter(
                    lambda bot_account: bot_account.hash == last_state['account_hash'],
                    bot_accounts
                )
            )

            continue_result = input(f'[Main] Continue account with private_key {last_bot_account.short_private_key}? [y/n]: ')
            if continue_result.lower() == 'y':
                bot_accounts = [bot_accounts[accounts_hashes.index(account_hash)] for account_hash in order]
                accounts_hashes = [bot_account.hash for bot_account in bot_accounts]
                bot_accounts = bot_accounts[last_bot_index + 1:]
                bot_accounts.insert(0, last_bot_account)
                logger.info(f'[Main] Continuing account with private_key {last_bot_account.short_private_key}')

    with open('last_state.json', 'w') as file:
        json.dump(
            {
                'order': accounts_hashes,
                'account_hash': bot_accounts[0].hash
            },
            file,
            indent=4
        )

    logger.info(f'Accounts order: {" -> ".join(bot_account.short_private_key for bot_account in bot_accounts)}')

    for bot_account in bot_accounts:
        logger.info(f'Processing account with private_key {bot_account.short_private_key}')

        utils.random_sleep.min_sleep_time = bot_account.min_sleep_time
        utils.random_sleep.max_sleep_time = bot_account.max_sleep_time

        if bot_account.mobile_proxy_changelink:
            response = requests.get(bot_account.mobile_proxy_changelink)
            if response.status_code == 200:
                logger.info(f'[Main] Changed mobile proxy for account with private_key {bot_account.short_private_key}: {response.text}')
                utils.sleep(5)
            else:
                logger.warning(f'[Main] Failed to change mobile proxy for account with private_key {bot_account.short_private_key}: {response.text}')

        if bot_account.proxy:
            proxy_error = False

            while True:
                try:
                    proxy_test_result = utils.test_proxy(bot_account.proxy)
                    if isinstance(proxy_test_result, str):
                        logger.info(f'[Main] Outgoing IP for account with private_key {bot_account.short_private_key} - {proxy_test_result}')
                        break
                    elif proxy_test_result:
                        logger.warning(f'[Main] Failed to get outgoing IP for account with private_key {bot_account.short_private_key}')
                        break
                    else:
                        logger.error(f'[Main] Proxy specified for account with private_key {bot_account.short_private_key} is not working. Retrying...')
                        logger.info(f'[Main] To stop retrying, press Ctrl+C')
                        utils.time.sleep(15)
                except KeyboardInterrupt:
                    proxy_error = True
                    break

            if proxy_error:
                proxy_result = input(
                    '[Main] What to do? (possible options: [s]kip, [e]xit, [d]elete (deletes proxy)): '
                )
                if proxy_result.lower() in {'s', 'skip'}:
                    logger.warning(f'[Main] Skipping account with private_key {bot_account.short_private_key}')
                    continue
                elif proxy_result.lower() in {'e', 'exit'}:
                    logger.error(f'[Main] Exiting session due to incorrect proxy')
                    break
                else:
                    logger.info(f'[Main] Deleting proxy for account with private_key {bot_account.short_private_key}')
                    bot_account.proxy = None

        while True:
            success = False

            for i in range(max(1, bot_account.max_retries)):
                result = register_and_claim(
                    private_key=bot_account.private_key,
                    network_name=enums.NetworkNames.Scroll,
                    username=bot_account.username,
                    invite_code=bot_account.invite_code,
                    claim_badges=bot_account.claim_badges,
                    proxy=bot_account.proxy
                )

                if result == enums.TransactionStatus.SUCCESS:
                    success = True
                    break

                if i < bot_account.max_retries - 1:
                    utils.random_sleep()
            else:
                logger.error(f'[Main] Failed to process account with private_key {bot_account.short_private_key}')

                if not bot_account.auto_skip:
                    answer = input('[Main] What to do? (possible options: [s]kip, [e]xit, [r]etry): ')

                    if answer.lower() in {'s', 'skip'}:
                        logger.warning(f'[Main] Skipping account with private_key {bot_account.short_private_key}')
                        break
                    elif answer.lower() in {'e', 'exit'}:
                        logger.error(f'[Main] Exiting session due to failed transaction')
                        return
                    else:
                        logger.info(f'[Main] Retrying account with private_key {bot_account.short_private_key}')
                        utils.random_sleep()

            if success:
                break

        logger.info(f'[Main] Finished account with private_key {bot_account.short_private_key}')


def main():
    logger.info(f'Scroll Canvas Bot started')

    bot_accounts = accounts_loader.read_accounts()

    if isinstance(bot_accounts, list):
        run_accounts(bot_accounts)


if __name__ == '__main__':
    main()
