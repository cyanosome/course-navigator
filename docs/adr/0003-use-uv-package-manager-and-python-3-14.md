# [ADR-0003] Python パッケージマネージャとしての uv 採用と Python 3.14 への追従

- **ステータス**: 承認済 (Accepted)
- **起票日**: 2026-06-18
- **決定者 / 議論の場**: yuto (@cyanosome)
- **関連リンク**: Commit `f0b7aec`, `backend/Dockerfile`, `backend/pyproject.toml`, `compose.yaml`

---

## 1. 背景と課題 (Context & Problem Statement)

- **Python パッケージ管理における再現性と速度の課題**
  - Python の Docker 環境構築においては、従来 `pip` と `requirements.txt` を用いるのがデフォルトかつ一般的であった。
  - しかし、`pip` 単体では推移的依存関係（ライブラリが依存するライブラリ）の厳密なバージョンロックが難しく、開発者間や CI 環境で「ある環境では動くが別の環境ではビルドが壊れる」という依存関係の不整合が発生しやすい。
  - 一方で、Poetry や pipenv などの既存のロックファイル対応ツールは依存関係解決が遅く、Docker コンテナのビルド時間が大幅に肥大化するストレスがあった。
- **宣言的でシンプルな構成管理の追求**
  - Dockerfile の中に `RUN pip install ...` を長々と書き連ねる命令型の手法を避け、`pyproject.toml` という現代の標準フォーマットで依存関係を一元管理したいという要求があった。

---

## 2. 決定の判断基準 (Decision Drivers)

- **依存解決およびインストール速度**: Docker のビルド時間や CI 実行時間を極小化できること。
- **Dockerfile 記述のシンプルさ**: Docker 環境の構築に余計なボイラープレートや複雑なスクリプトを必要としないこと。
- **再現性（Reproducibility）**: ロックファイル（`uv.lock`）により、チーム全員が常にバイト単位で同一のライブラリバージョンを共有できること。
- **標準仕様への準拠と将来性**: PEP 517 / 518 / 621（`pyproject.toml`）に準拠し、最新の Python 3.14 ランタイムで統一できること。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: `pip` + `requirements.txt`（デフォルトのクラシック構成）**
   - Python に同梱されている標準の `pip` をそのまま使用し、`requirements.txt` にライブラリを列挙する。
2. **選択肢 B: `Poetry` / `pipenv`（既存のロックツール）**
   - `pyproject.toml` や `Pipfile.lock` を用いて仮想環境とロックファイルを厳密に管理する。
3. **選択肢 C: `uv` (Astral 製) + Python 3.14 【採用】**
   - Rust 製の次世代高速パッケージマネージャ `uv` を採用し、公式 Docker イメージ（`ghcr.io/astral-sh/uv:python3.14-alpine`）をベースに `uv.lock` で同期する。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 C: `uv` パッケージマネージャと Python 3.14 の採用**

### 選定理由
1. **圧倒的なビルド・インストール速度**:
   - `uv` は Rust でゼロから実装されており、pip や Poetry と比較して依存解決・キャッシュ利用・並列ダウンロードが数十倍高速である。Docker イメージのビルドや `uv sync` が瞬時に完了し、開発体験が飛躍的に向上する。
2. **Docker との抜群の親和性と導入の簡潔さ**:
   - Astral 公式のベースイメージ `ghcr.io/astral-sh/uv:python3.14-alpine` をそのまま `FROM` で指定するだけで即座に `uv` 環境が整う。
   - `COPY pyproject.toml uv.lock ./` と `RUN uv sync --frozen --no-install-project` を記述するだけで、キャッシュを最大限に効かせた堅牢なビルドパイプラインがわずか数行で実現できる。
3. **`pyproject.toml` による宣言的管理**:
   - Dockerfile 内に個別パッケージを列挙するのではなく、`pyproject.toml` にアプリケーションのメタデータと依存関係を宣言的に記述できるため、可読性と保守性が大幅に向上する。
4. **当時の最新・最長サポートラインとしての Python 3.14 の選定**:
   - プロジェクト発足時（2026年6月）において、フロントエンドで Node.js 24 LTS を採用したのと同様に、バックエンドも「立ち上げ時点で利用可能な最新かつサポート期間が最長となるバージョン」をベースラインに据える方針をとった。
   - Astral の uv 公式 Docker イメージでも `python3.14-alpine` が最新安定ラインとして提供されており、将来的な言語仕様の非推奨化やアップグレード負債を早期に抱え込むリスクを回避した。
   - これにより、インタプリタの最適化や型ヒントの遅延評価といった最新言語機能の恩恵をフルに享受できる。

---

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: `pip` + `requirements.txt`
- **メリット (+)**:
  - 追加ツールの学習や導入が一切不要で、最も普及している。
- **デメリット・見送り理由 (-)**:
  - 依存解決が遅く、ハッシュ付きロックを行わない限り環境の完全な再現性が担保できない。
  - パッケージ追加・削除時のクリーンな同期（不要になったパッケージの自動削除）が困難。

### 選択肢 B: `Poetry` / `pipenv`
- **メリット (+)**:
  - ロックファイルによる厳密な再現性が得られる。
- **デメリット・見送り理由 (-)**:
  - 依存関係の解決アルゴリズムが重く、Docker ビルドに数分単位の時間がかかる。
  - Docker コンテナ内にインストールするためのセットアップ手順がやや煩雑。

### 選択肢 C: `uv` + Python 3.14 【採用案】
- **メリット (+)**:
  - ミリ秒単位の圧倒的な依存解決・インストール速度。
  - `ghcr.io/astral-sh/uv` 公式イメージにより、Dockerfile の記述が極めてシンプル。
  - `uv.lock` による決定論的で完全な再現性の担保。
  - 最長サポート期間を持つ最新ランタイムの確保。
- **デメリット・受容するリスク (-)**:
  - 比較的新しいツールおよび言語バージョンであるため、Alpine 上での一部 C 拡張パッケージのビルド設定や、ホスト側仮想環境との住み分けに配慮が必要（詳細は後述）。

---

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - コンテナの初回ビルドおよびライブラリ追加後の再同期が極めて高速化された。
  - 開発者全員が `uv.lock` を介して同一の依存環境を確実に再現できるようになった。
  - `compose.yaml` の起動コマンドも `uv run fastapi dev main.py` として一元化され、仮想環境のパスを意識せずシンプルに起動可能となった。
- **留意点・開発運用上のトレードオフ (Caveat)**:
  - **Alpine Linux 上での C 拡張パッケージ（`asyncpg`）のビルド対応**:
    - 最新の Python 3.14 かつ Alpine Linux（musl libc）環境では、一部の C 拡張ライブラリ（特に非同期 PostgreSQL ドライバの `asyncpg` 等）の事前ビルド済み binary wheel が PyPI 上にまだ提供されていない場合がある。
    - そのため、`backend/Dockerfile` に `apk add --no-cache gcc musl-dev python3-dev` を明示的に追加し、ソースからコンパイルできるように設定した（コミット `fa9c04d`）。最新ランタイムの恩恵を得るための必要コストとして受容している。
  - **ホストとコンテナの `.venv` の分離への意識**:
    - 本プロジェクトの `compose.yaml` では、ホスト側のカレントディレクトリをコンテナの `/backend_app` にボリュームマウントしつつ、コンテナ内の仮想環境 `/backend_app/.venv` を匿名ボリュームで保護（シャドウイング）している。
    - そのため、ホスト側のローカル PC でも日常的に `uv` を使用している場合、VS Code 等のエディタがホスト側のローカル `.venv` を自動認識・アクティベートすることがある。
    - **ホスト側の仮想環境でパッケージを追加・変更しても、コンテナ内部には直接反映されない**（逆も同様）。
    - したがって、パッケージの追加・更新を行う際は以下のいずれかの運用ルールを徹底する：
      1. `make shell` でコンテナに入って `uv add <package>` を実行する。
      2. ホスト側で `uv add <package>`（または `uv lock`）を実行した上で、コンテナを再ビルド（`docker compose build backend`）する。

---

## 7. 参考資料 (References)

- [uv Official Documentation (Astral)](https://docs.astral.sh/uv/)
- [uv Docker Guide](https://docs.astral.sh/uv/guides/docker/)
- [ghcr.io/astral-sh/uv Container Images](https://github.com/astral-sh/uv/pkgs/container/uv)
- [PEP 621 – Storing project metadata in pyproject.toml](https://peps.python.org/pep-0621/)
