"""tests/eval のテストから backend/eval（評価ハーネス）と tests/fake_graph.py を import できるようにする。

backend/eval は配布パッケージ（src/ 配下）に入っていないので、backend ルートを sys.path に足す。
tests/eval には __init__.py を置かない（置くと `eval` という名前のパッケージとして本物とぶつかる）。
"""

import sys
from pathlib import Path

_TESTS_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _TESTS_ROOT.parent

for path in (_BACKEND_ROOT, _TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
