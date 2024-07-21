import datetime as dt
import random
import re
import time

import requests
from eth_typing.encoding import HexStr
from eth_typing.evm import Hash32
from hexbytes.main import HexBytes
from web3 import Web3
from web3.eth.eth import Eth
from web3.types import TxReceipt

import constants
import enums
from logger import logger


def sleep(sleep_time: float):
    logger.info(f'[Sleep] Sleeping for {round(sleep_time, 2)} seconds. If you want to skip this, press Ctrl+C')
    try:
        time.sleep(sleep_time)
    except KeyboardInterrupt:
        logger.info('[Sleep] Skipping sleep')


def random_sleep():
    min_sleep_time = getattr(random_sleep, 'min_sleep_time', 1)
    max_sleep_time = getattr(random_sleep, 'max_sleep_time', 10)
    sleep_time = round(random.uniform(min_sleep_time, max_sleep_time), 2)
    sleep(sleep_time)


def test_proxy(proxy: dict[str, str]) -> str | bool:
    try:
        response = requests.get(
            url='https://geo.geosurf.io/',
            proxies=proxy,
            timeout=5
        )
    except KeyboardInterrupt:
        raise
    except Exception:
        try:
            response = requests.get(
                url='https://google.com',
                proxies=proxy,
                timeout=5
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            return False
        else:
            return True
    else:
        ip_json = response.json()
        if 'ip' in ip_json:
            ip = ip_json['ip']
            country = ip_json['country']
            return f'{ip} ({country})'
        else:
            return True


def wait_for_transaction_receipt(
    web3: Eth,
    txn_hash: Hash32 | HexBytes | HexStr,
    timeout: int = 300,
    logging_prefix: str = 'Receipt',
    return_on_fail: bool = False
) -> TxReceipt:
    start_time = dt.datetime.now()
    while True:
        try:
            receipt = web3.wait_for_transaction_receipt(
                transaction_hash=txn_hash,
                timeout=timeout - (dt.datetime.now() - start_time).total_seconds()
            )
        except Exception as e:
            logger.warning(f'[{logging_prefix}] Exception occured while waiting for transaction receipt: {e}')
            if dt.datetime.now() - start_time >= dt.timedelta(seconds=timeout):
                if return_on_fail:
                    return None
                else:
                    answer = input(f'[{logging_prefix}] Failed to get transaction receipt. Press Enter when transaction will be processed')
                    try:
                        receipt = web3.wait_for_transaction_receipt(
                            transaction_hash=txn_hash,
                            timeout=5
                        )
                    except Exception as e:
                        logger.error(f'[{logging_prefix}] Failed to get transaction receipt: {e}')
                        return None
            time.sleep(min(5, timeout / 10))
        else:
            return receipt


def suggest_gas_fees_metamask(
    network_name: enums.NetworkNames,
    proxy: dict[str, str] = None
):
    last_update = getattr(suggest_gas_fees_metamask, 'last_update', dt.datetime.fromtimestamp(0))
    last_network = getattr(suggest_gas_fees_metamask, 'network_name', None)

    if dt.datetime.now() - last_update > dt.timedelta(seconds=10) or last_network != network_name:
        gas_price = None
        network = constants.NETWORKS[network_name]

        while True:
            try:
                response = requests.get(
                    url=f'https://gas-api.metaswap.codefi.network/networks/{network_name.value}/suggestedGasFees',
                    proxies=proxy
                )
            except Exception:
                logger.warning(f'[Gas] Failed to get gas price for {network_name}')
                sleep(10)
                continue
            else:
                if response.status_code != 200:
                    logger.warning(f'[Gas] Failed to get gas price for {network_name}')
                    sleep(10)
                    continue
                gas_json = response.json()
                medium_gas = gas_json['medium']
                gas_gwei = float(medium_gas['suggestedMaxFeePerGas'])
                gas_price = {
                    'maxFeePerGas': Web3.to_wei(gas_gwei, 'gwei'),
                    'maxPriorityFeePerGas': Web3.to_wei(medium_gas['suggestedMaxPriorityFeePerGas'], 'gwei')
                }

            if not network.max_gwei or float(gas_gwei) <= network.max_gwei:
                break

            logger.info(f'[Main] Current gas price {round(gas_gwei, 3)} Gwei is higher than max {network.max_gwei} Gwei in {network_name} network')

            sleep(10)

        suggest_gas_fees_metamask.gas_price = gas_price
        suggest_gas_fees_metamask.last_update = dt.datetime.now()
        suggest_gas_fees_metamask.network_name = network_name

        return gas_price
    else:
        return getattr(suggest_gas_fees_metamask, 'gas_price', None)


def suggest_gas_fees(
    network_name: enums.NetworkNames,
    proxy: dict[str, str] = None
):
    last_update = getattr(suggest_gas_fees, 'last_update', dt.datetime.fromtimestamp(0))
    last_network = getattr(suggest_gas_fees, 'network_name', None)

    if dt.datetime.now() - last_update > dt.timedelta(seconds=10) or last_network != network_name:
        network = constants.NETWORKS[network_name]

        if network.rabby_id is None:
            return suggest_gas_fees_metamask(network_name, proxy)

        while True:
            if network_name == enums.NetworkNames.Scroll:
                suggest_gas_fees(enums.NetworkNames.ETH, proxy)

            try:
                response = requests.get(
                    url=f'https://api.rabby.io/v1/wallet/gas_market?chain_id={network.rabby_id}',
                    headers={
                        'X-Api-Ver': 'v2',
                        'X-Client': 'Rabby',
                        'X-Version': '0.92.52',
                        'X-Api-Nonce': 'n_0LknmB7aJePWhQezXR3SFQeLmf0Q3wDDnSpgDJxS',
                        'X-Api-Sign': '058c4e73eb35b19a57ffca66643937e447dcacd9a3c653df774fb7c45e328462',
                        'X-Api-Ts': '1709038705'
                    },
                    proxies=proxy
                )
            except Exception:
                logger.warning(f'[Gas] Failed to get gas price for {network_name} on Rabby')
                return suggest_gas_fees_metamask(network_name, proxy)
            else:
                if response.status_code != 200:
                    logger.warning(f'[Gas] Failed to get gas price for {network_name} on Rabby')
                    return suggest_gas_fees_metamask(network_name, proxy)

                gas_json = response.json()
                normal_gas = gas_json[1]

                gas_wei = int(normal_gas['price'])
                gas_gwei = Web3.from_wei(gas_wei, 'gwei')
                priority_gas = normal_gas.get('priority_price', None)

                if not network.max_gwei or float(gas_gwei) <= network.max_gwei:
                    break

                logger.info(f'[Main] Current gas price {round(gas_gwei, 3)} Gwei is higher than max {network.max_gwei} Gwei in {network_name} network')

                sleep(10)

        if priority_gas is not None:
            gas_price = {
                'maxFeePerGas': gas_wei,
                'maxPriorityFeePerGas': int(priority_gas)
            }
        else:
            gas_price = {
                'gasPrice': gas_wei
            }

        suggest_gas_fees.gas_price = gas_price
        suggest_gas_fees.last_update = dt.datetime.now()
        suggest_gas_fees.network_name = network_name

        return gas_price
    else:
        return getattr(suggest_gas_fees, 'gas_price', None)


def estimate_gas(
    web3: Web3,
    txn: dict
) -> int:
    return int(web3.eth.estimate_gas(txn) * 1.25)


def check_username(username: str) -> bool:
    if re.match(r'^[A-Za-z0-9_]{4,15}$', username):
        return True
    return False


def check_invite_code(invite_code: str) -> bool:
    if re.match(r'^[A-Z0-9]{5}$', invite_code):
        return True
    return False
