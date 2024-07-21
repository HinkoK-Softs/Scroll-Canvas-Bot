import json
from dataclasses import dataclass
from pathlib import Path

import enums


@dataclass
class Network:
    chain_id: int
    name: str
    rpc_url: str
    txn_explorer_url: str
    max_gwei: float
    rabby_id: str

    def __repr__(self):
        return f'{self.name} (ID: {self.chain_id})'


with open(Path(__file__).parent / 'RPC.json') as file:
    rpc_list = json.load(file)

with open(Path(__file__).parent / 'MaxGwei.json') as file:
    max_gwei = json.load(file)

NETWORKS = {
    enums.NetworkNames.ETH: Network(
        chain_id=1,
        name='Ethereum Mainnet',
        rpc_url=rpc_list.get(
            enums.NetworkNames.ETH.name,
            'https://rpc.ankr.com/eth'
        ),
        txn_explorer_url='https://etherscan.io/tx/',
        max_gwei=max_gwei.get(enums.NetworkNames.ETH.name, None),
        rabby_id='eth'
    ),
    enums.NetworkNames.Scroll: Network(
        chain_id=534352,
        name='Scroll',
        rpc_url=rpc_list.get(
            enums.NetworkNames.Scroll.name,
            'https://rpc.ankr.com/scroll'
        ),
        txn_explorer_url='https://scrollscan.com/tx/',
        max_gwei=max_gwei.get(enums.NetworkNames.Scroll.name, None),
        rabby_id='scrl'
    )
}
