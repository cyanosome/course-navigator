"""画面の AI の口（navi-v1）。変種の因子をリクエストごとに当てて既存の runner を呼ぶ。"""

from fastapi import APIRouter

router = APIRouter(tags=["assist"])
