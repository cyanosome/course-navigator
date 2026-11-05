"""学科・科目のデータ API（navi-v1）。

画面はデータを JSON で抱えず、このルーターを通して DB に逐次問い合わせる。
"""

from fastapi import APIRouter

router = APIRouter(tags=["catalog"])
