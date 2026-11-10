"""navi-v1 の約束の版を応答のヘッダで示す（api-contract.md 1 章）。

11/13 までは項目を消さない・意味を変えない（足すのはよい）。版を上げるときはここだけを変える。
"""

from typing import Final

from fastapi import Response

__all__ = ["CONTRACT_HEADER", "CONTRACT_VERSION", "set_contract_header"]

CONTRACT_HEADER: Final = "X-Navi-Contract"
CONTRACT_VERSION: Final = "navi-v1"


async def set_contract_header(response: Response) -> None:
    """ルーターの dependencies に置く。成功の応答に約束の版のヘッダを付ける。"""
    response.headers[CONTRACT_HEADER] = CONTRACT_VERSION
