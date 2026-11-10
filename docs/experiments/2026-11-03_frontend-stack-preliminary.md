# フロントエンドの技術と配信先を決めるための予備計測（ビルド・送る量・GMS への疎通）

| 項目 | 内容 |
|---|---|
| 実験者 | Aki_Ha（個人の予備実験。チームの本実験ではない）。計測のコマンドは、Aki_Ha の依頼で Claude Code（実行役）が Aki_Ha の PC で流した |
| 実施日 | 2026-11-03（JST）17:01 頃〜17:21 |
| 何を確かめたか | ①今のフロント（`origin/main` 14f8d57）のビルド時間と、初回に送る JS・CSS の大きさ ②フレームワークの雛形どうしの JS の大きさ ③Vite の開発サーバーで配る場合とビルドした成果物を配る場合の、リクエスト数と転送量 ④公開先の GMS サーバーに学外から届くか |
| 結論 | 今のフロントの初回の JS は gzip 後 75,688 B、ビルドは 9〜15 秒。雛形どうしでは React 68,374 B に対して Svelte 12,241 B・Preact 7,379 B。同じ画面を開くと、開発サーバーは 25 リクエスト・1,697,392 B、ビルド版は 4 リクエスト・92,366 B（約 18 分の 1）。GMS は学外から HTTP→HTTPS の 308 は返るが、証明書は Traefik の既定の自己署名で、検証を外しても `/` と `/api/docs` が 404。各条件 1〜3 回の計測で、ばらつきは見ていない |

関連: 要件の一覧は [`docs/frontend/requirements.md`](../frontend/requirements.md)（Aki_Ha の案。R 番号と G 番号はここから取った）。待ち時間の数字は [`2026-10-11_test3-2-e2e.md`](2026-10-11_test3-2-e2e.md) から引いた。

## 1. 目的と問い

10/28 の定例 MTG で Aki_Ha がフロントエンドの担当になり、関西大学の学生へのインタビューで使う画面を作ることになった。今のフロントは疎通テスト用のページで、作り直す。11/4（水）の定例 MTG で、作り直しの技術（今の React + Vite を続けるか、ほかにするか）と、フロントをどこに置くかを決める。その材料として、安く測れる範囲で次の4つを測った。依頼元は Aki_Ha。

- Q-a 今のフロント（`origin/main` 14f8d57）のビルド時間と、初回に送る JS・CSS の大きさ（gzip 後）は
- Q-b フレームワークの雛形どうしで、初回の JS はどれくらい違うか（React / Svelte / Preact / Next.js）
- Q-c Vite の開発サーバーで配る場合と、ビルドした成果物を配る場合で、初回のリクエスト数と転送量はどれくらい違うか（今の `compose.yaml` は、フロントを開発サーバーで出している）
- Q-d 公開先の GMS サーバーは、学外から開けるか

比較の実験ではなく、判断の材料を集めるための計測である。LLM は使っていない。

## 2. 仮説

事前登録は無い（測る前に文書にしなかった）。測る前の見込みは「React + router は gzip 後 70〜80 KB」「開発サーバーはビルド版の数倍以上」だったが、これは測った後に書き留めたもので、検証の基準には使えない。合否の数値基準も決めていない。

## 3. 実行環境

| 項目 | 値 |
|---|---|
| 日時（JST） | 2026-11-03。Q-a 17:02:40〜17:04 頃、Q-b 17:05:51〜17:15:51（10 分で打ち切り）、Q-c 17:17 頃、Q-d 17:06 と 17:21:32 |
| PC | Windows 11 Home 10.0.26200（Aki_Ha の PC）。Git Bash から実行。Docker は使っていない |
| ネットワーク | Aki_Ha の家庭の回線（学外）。通信の制限（スロットリング）はかけていない |
| Node / npm | v24.13.1 / 11.8.0 |
| 対象のコミット | `origin/main` = `origin/frontend` = 14f8d57（2026-10-31 03:39 JST） |
| 今のフロントの実際の版 | react 19.2.7、react-dom 19.2.7、react-router-dom 6.30.4、vite 8.0.16、typescript 6.0.3（14f8d57 の `frontend/package-lock.json`） |
| 雛形 | `npm create vite@9.3.3`（テンプレート react-ts / svelte-ts / preact-ts。入った版は vite ^8.3.5、react ^19.3.1、svelte ^5.57.2、preact ^11.0.2）、`create-next-app@16.4.4` |
| ブラウザ（Q-c） | Claude Code デスクトップの Browser ペイン（Chromium 系と推定）。キャッシュの無い新しいタブで開いた |
| gzip | 17:48 にサイズを計算し直したときは gzip 1.14（9 節）。元の計算のときの版は記録していない（同じ PC の Git Bash） |
| curl / openssl（Q-d） | 版は記録していない |
| Rust | 入っていない（`cargo --version` が command not found、`~/.cargo` も `~/.rustup` も無い） |
| LLM・API の枠・MCP | 該当なし（使っていない） |

## 4. データ

測ったのはソフトウェアそのもので、利用者のデータや質問は使っていない。

- 今のフロント: `git archive origin/main frontend` で取り出したもの。疎通テストの 5 ページ（`/test2-1`〜`/test3-2`）と Welcome のページがあり、`BrowserRouter` で全ページを最初に読み込む（`frontend/src/App.tsx`）。チャット画面ではないので、作り直した後の重さとは違う
- 雛形: 各テンプレートの初期状態（カウンターのボタンとロゴだけ）。フレームワークの最低限の重さで、ルーターや Markdown の表示は入っていない
- GMS サーバー: 駒澤大学 GMS 学部のサーバーで、インタビューで使う予定の公開先。公開リポなので、ホスト名と IP アドレスはここには書かず、以下 `$GMS_HOST` と書く（ホスト名はチームで共有済み。生データには残っている。12 節）

## 5. 条件

| 条件 | 中身 | 偏り・注意 |
|---|---|---|
| current | 今のフロント（4 節）をそのまま `npm ci` と `npm run build`（`tsc -b && vite build`） | チャット画面ではない |
| vite-react-ts / vite-svelte-ts / vite-preact-ts | 雛形を作り、`npm install` と `npm run build` | build の中身がテンプレートで違う（react-ts と preact-ts は `tsc -b && vite build`、svelte-ts は `vite build` だけ） |
| next-app | create-next-app の初期状態に `output: "export"`（静的書き出し）を足して `npm run build` | 10 分の上限内に終わらず、測れなかった |
| dev | current を `npx vite`（開発サーバー）で配り、`/` を開いた | ローカル（127.0.0.1）で、Traefik は通していない。開発サーバーは圧縮しなかった |
| preview | current のビルド成果物を `npx vite preview` で配り、`/` を開いた | `vite preview` は gzip で圧縮して返した（転送量が gzip 後の大きさと合う）。本番の Traefik は compress ミドルウェアを設定していない（`compose.yaml`）ので、本番で圧縮されるかは確かめていない |
| GMS | 学外から `curl` と `openssl` で、HTTP・HTTPS の応答と証明書を見た | 学外の 1 か所から 2 回だけ |

## 6. 手順

以下 `S` は作業フォルダ（Aki_Ha の PC の一時フォルダ）、`$GMS_HOST` は GMS のホスト名。スクリプト 3 本の全文は付録 A にある。

```bash
# Q-a 今のフロント
cd <このリポ>
git archive --format=tar --prefix=current/ origin/main frontend | tar -x -C "$S/bench"
bash "$S/scripts/measure.sh" "$S/bench/current/frontend" "$S/bench/run1.log"   # npm ci と 1 回目の build
cd "$S/bench/current/frontend" && for i in 2 3; do t0=$EPOCHREALTIME; npm run build > "$S/bench/build_run$i.log" 2>&1; t1=$EPOCHREALTIME; awk -v a=$t0 -v b=$t1 -v i=$i 'BEGIN{printf "run%s build_sec=%.1f\n", i, b-a}'; done   # 2 回目・3 回目
bash "$S/scripts/sizes.sh" "$S/bench/current/frontend/dist"

# Q-b 雛形（全体を 10 分で打ち切る）
timeout 600 bash "$S/scripts/scaffold_bench.sh" "$S/bench/scaffold" > "$S/bench/scaffold_summary.log"
for t in react-ts svelte-ts preact-ts; do bash "$S/scripts/sizes.sh" "$S/bench/scaffold/vite-$t/dist"; done

# Q-c 開発サーバーとビルド版（current のディレクトリで、それぞれ別の端末で）
npx vite --port 5199 --strictPort --host 127.0.0.1
npx vite preview --port 5198 --strictPort --host 127.0.0.1
# ブラウザの新しいタブで http://127.0.0.1:5199/ と http://127.0.0.1:5198/ を開き、2.5 秒待ってから開発者ツールのコンソールで:
#   const nav=performance.getEntriesByType('navigation')[0]; const res=performance.getEntriesByType('resource');
#   const sum=(a,k)=>a.reduce((s,e)=>s+(e[k]||0),0);
#   ({requests_total:res.length+1, transfer_bytes_total:sum(res,'transferSize')+nav.transferSize, decoded_bytes_total:sum(res,'decodedBodySize')+nav.decodedBodySize})

# Q-d GMS
curl -sI -m 15 "http://$GMS_HOST/"
echo | openssl s_client -connect "$GMS_HOST:443" -servername "$GMS_HOST" 2>/dev/null | openssl x509 -noout -subject -issuer -dates
curl -sk -m 15 -o /dev/null -w "%{http_code}\n" "https://$GMS_HOST/"
curl -sk -m 20 -o /dev/null -w "%{http_code}\n" "https://$GMS_HOST/api/docs"
```

順序は Q-a → Q-b（裏で実行中に Q-d の 1 回目）→ Q-c → Q-d の 2 回目。回数は Q-a の build が 3 回、npm ci が 1 回、ほかは 1 回ずつ（Q-d は 2 回）。予算の上限は Q-b の 10 分だけ決めた。

再現するときの注意: npm のキャッシュの状態で install の時間は大きく変わる。雛形の版は `create-vite` と `create-next-app` の版を固定しても、依存の `^` の範囲で変わりうる。

## 7. 指標の定義

| 指標 | 定義 |
|---|---|
| npm ci 秒・build 秒 | コマンドの開始から終了までの壁時計の時間。bash の `$EPOCHREALTIME` の差（秒、小数 1 桁） |
| vite 部分の秒 | `vite build` が出す「built in ○ms」。build 秒から引いた残りが主に `tsc -b`（型チェック） |
| 生バイト | ビルド成果物のファイルの大きさ（`wc -c`） |
| gzip 後バイト | `gzip -9 -c ファイル \| wc -c`。Vite の表示（「gzip: ○ kB」）とは圧縮の設定が違うので少しずれる（例: 同じ JS が Vite の表示では 76.99 kB） |
| リクエスト数 | `performance.getEntriesByType('resource')` の件数 + 1（HTML 本体） |
| 転送バイト | 上の各エントリと navigation エントリの `transferSize` の合計（ヘッダーを含む、圧縮後） |
| 展開後バイト | 同じく `decodedBodySize` の合計 |

計算の例（preview、付録 B の JSON の `all`）:
- 転送バイト = JS 76,470 + CSS 1,773 + PNG 13,357 + HTML 本体 = 92,366。HTML 本体の分は差し引きで 92,366 − 91,600 = 766
- 展開後バイト = 252,203 + 4,105 + 13,057 + HTML 本体 466 = 269,831（466 は `index.html` の生バイトと一致する）
- 比 = dev の転送バイト 1,697,392 ÷ preview の 92,366 = 18.4（約 18 分の 1）。リクエスト数は 25 ÷ 4 = 6.25（約 6 倍）

## 8. 結果

### 8.1 Q-a 今のフロント（`origin/main` 14f8d57）

| 回 | npm ci 秒 | build 秒 | うち vite 部分 | 備考 |
|---|---|---|---|---|
| 1 | 41.8 | 15.0 | 0.92 | npm ci の直後。`tsc -b` の増分キャッシュなし |
| 2 | — | 9.0 | 0.42 | `tsc -b` の増分キャッシュあり |
| 3 | — | 9.6 | 0.83 | 同上 |

各列: 「npm ci 秒」は依存の取得、「build 秒」は `npm run build` 全体、「うち vite 部分」はそのうち Vite のバンドルにかかった秒。2・3 回目の build 秒はコマンドの画面出力を写したもので、ファイルには残っていない（12 節）。

| ファイル | 生バイト | gzip 後バイト |
|---|---|---|
| `assets/index-*.js` | 252,203 | 75,688 |
| `assets/index-*.css` | 4,105 | 1,489 |
| `index.html` | 466 | 309 |
| （参考）`assets/hero-*.png` | 13,057 | — |

各列: 7 節の定義どおり。初回の表示に要る JS はこの 1 ファイルだけ（全ページを最初に読み込むため）。

### 8.2 Q-b 雛形の初回の JS（初期状態のまま）

| 条件 | 作成 + install 秒 | build 秒 | JS 生バイト | JS gzip 後バイト |
|---|---|---|---|---|
| vite-react-ts | 42.5 | 6.8 | 222,447 | 68,374 |
| vite-svelte-ts | 41.2 | 13.6 | 30,766 | 12,241 |
| vite-preact-ts | 44.2 | 14.5 | 18,093 | 7,379 |
| next-app（静的書き出し） | 約 430（17:08 頃〜17:15:48） | 打ち切り | 未測定 | 未測定 |

各列: 「作成 + install 秒」は雛形の作成と `npm install` の合計で、npm のキャッシュの状態の影響が入る。「build 秒」はテンプレートの scripts の違い（`tsc -b` の有無など。5 節）を含むので、フレームワークの速さの比較には使えない。JS の 2 列は 7 節の定義どおり。next-app は作成と install で約 7 分かかり（npm の表示では install が「in 6m」）、ビルドの開始から約 3 秒で 10 分の上限に達して打ち切られた。

### 8.3 Q-c 開発サーバーとビルド版（current の `/` を開いたとき）

| 条件 | リクエスト数 | 転送バイト | 展開後バイト | うち JS（展開後） | 大きいもの（展開後バイト） |
|---|---|---|---|---|---|
| dev（`vite`） | 25 | 1,697,392 | 1,689,892 | 1,676,212（23 件） | `react-dom_client.js` 820,919 / `@vite/client` 209,993 / `react-router-dom.js` 201,230 / `@react-refresh` 111,894 |
| preview（ビルド版） | 4 | 92,366 | 269,831 | 252,203（1 件） | JS（転送 76,470） |

各列: 7 節の定義どおり。「うち JS」の件数は、dev では JS として配られたもの（`/@vite/client`・`/src/*.tsx` などを含む）の数。値はブラウザのコンソールの集計結果を写したもの（付録 B）。生データの JSON には `load_event_ms`（dev 537、preview 379）もあるが、計算式を記録していないので指標には使わない。

### 8.4 Q-d GMS サーバー（17:06 と 17:21:32 の 2 回、学外から。結果は同じ）

| 確認 | 結果 |
|---|---|
| `http://$GMS_HOST/` | 308 Permanent Redirect → `https://$GMS_HOST/` |
| HTTPS の証明書 | subject・issuer とも `CN=TRAEFIK DEFAULT CERT`（自己署名）。notBefore 2026-11-01 03:34:26 GMT、notAfter 2027-11-01 03:34:26 GMT |
| 証明書を検証して `/` | 接続できない（curl の exit 60。Windows の curl のエラーは `SEC_E_UNTRUSTED_ROOT`。ファイルに残っているのは exit コードだけ） |
| 証明書の検証を外して `/` | 404（`text/plain`。本文は `404 page not found`） |
| 証明書の検証を外して `/api/docs` | 404 |

17:06 の 1 回目の出力はファイルに残していない。17:21:32 の 2 回目は付録 B にある。

## 9. 事前登録との照合

事前登録は無いので、仮説の判定はしない。計画から変わったこと:

- Next.js は 10 分の上限内に終わらず、測れなかった。上限を延ばして測り直すことはしていない
- Rust/WASM（Leptos・Dioxus）は、ツールチェーンが入っていないので測っていない
- gzip 後の大きさ（8.1・8.2 の表）は、元の計算の出力をファイルに残していなかった。17:48 に、残っていたビルド成果物（17:04〜17:08 に作られ、その後に作り直していないことをファイルの更新時刻で確かめた）に同じスクリプト `sizes.sh` をもう一度かけて保存した（付録 B の `sizes_regenerated.tsv`）。表の値とすべて一致した

## 10. 考察

言えること:

- Q-a: 今のフロントの初回の JS は gzip 後 76 KB で、`requirements.md` の G4（150 KB 以下。今の約 2 倍までという自分たちの目安で、業界の基準値ではない）の半分。作り直しで Markdown の表示などを足しても、目安に収まる余地がある（推定）。ビルドは 9〜15 秒で、締め切りまでの作業の妨げにはならない
- Q-b: フレームワークだけを比べると、React（68 KB）に対して Svelte は 12 KB、Preact は 7 KB で、差は約 60 KB。遅い 4G（1.6 Mbps と仮定）なら約 0.3 秒（60 KB × 8 ÷ 1.6 Mbps。推定）。1 問の回答の待ち時間 53〜93 秒（[e2e の記録](2026-10-11_test3-2-e2e.md)、シードで 3 問各 1 回）に比べて小さく、送る量だけを理由に技術を変える根拠としては弱い
- Q-c: 本番で開発サーバーのまま配ると、同じ画面で転送量が約 18 倍（1.70 MB 対 92 KB）、リクエスト数が約 6 倍（25 対 4）になる。開発用の React（`react-dom_client.js` が 821 KB）がそのまま送られている。スマホのモバイル回線では、ここを直すのが一番効く（`requirements.md` の R3-5）
- Q-d: 学外から通信は届く（308 と TLS の応答が返った）が、今のままでは協力者に使ってもらえない。自己署名の証明書は 2026-11-01 03:34 GMT（JST 12:34）に作られているので、その頃に Traefik が起動し直し、正規の証明書を持たずに動いている見込み（推定）。HTTP が HTTPS に送られる設定と、ルーターが `web`（80）だけに付いている今の compose（`compose.yaml` の `entrypoints=web`）が組み合わさると、HTTPS 側に合うルーターが無く 404 になる（推定。サーバーの実際の設定は見ていない）

言えないこと:

- 作り直した後のチャット画面の重さ（部品で変わる）、表示の速さ（LCP など）、実機のスマホとモバイル回線での体感
- Next.js と Rust/WASM の大きさ（測れていない）
- 学内からの GMS の見え方と、サーバーの中の設定

## 11. 限界

- 各条件 1〜3 回しか測っていない。npm ci は 1 回で、npm のキャッシュの状態で大きく変わる
- 雛形はチャット画面ではない。作り直し後の重さは、使う部品で変わる
- Next.js は 10 分の上限内に終わらず測れなかった（create-next-app の作成と install に約 7 分かかり、ビルドの開始直後に打ち切った）。Rust/WASM はツールチェーンが無く測れなかった
- 開発サーバーとビルド版の比較はローカル（127.0.0.1）で、Traefik・GMS・実際のスマホ・モバイル回線は通していない。圧縮の有無は配り方で変わる（`vite preview` は圧縮し、開発サーバーは圧縮しなかった）
- GMS の確認は 2 回、学外の 1 か所から。1 回目の出力は残していない
- 2・3 回目の build 秒と Q-c の値は、画面やコンソールの出力を写したもの。gzip 後の大きさは後から計算し直したもの（9 節）

## 12. 生データとコードの場所

| 内容 | 場所 |
|---|---|
| 計測のスクリプト（`measure.sh`・`sizes.sh`・`scaffold_bench.sh`） | 付録 A に全文。ファイルは Aki_Ha の vault（非公開）の `10_projects/course-navigator/notes/frontend/2026-11-03_stack-bench/scripts/` |
| 生データ（ログ・JSON・TSV） | 付録 B に、Q-a・Q-c・Q-d のものと Q-b の要約を写した。全ファイル（雛形の作成・install・build のログを含む）は同じフォルダの `bench/`。リポには入れていない |
| 計測の対象のコード | `origin/main` 14f8d57 の `frontend/`（`package.json`・`package-lock.json`・`vite.config.ts`・`src/`） |
| ビルド成果物 | 残していない（6 節の手順で作り直せる） |
| 判断の材料にまとめた文書 | 技術の比較と配信先の比較は Aki_Ha の vault の同じフォルダの `stack-and-hosting.md`（非公開）。要件は [`docs/frontend/requirements.md`](../frontend/requirements.md) |

付録 B のログは、端末の制御文字（色の指定と、行を消して先頭に戻す `ESC[2K` と復帰）を除き、GMS のホスト名を `$GMS_HOST` に置き換えた。ほかは変えていない。

## 付録 A: スクリプト

`measure.sh`

```bash
#!/usr/bin/env bash
# 使い方: measure.sh <frontend ディレクトリ> <ログ出力先>
# npm ci と npm run build の所要時間（壁時計・秒）を測ってログに書く
set -u
DIR="$1"; LOG="$2"
cd "$DIR" || exit 1
el() { awk -v a="$1" -v b="$2" 'BEGIN{printf "%.1f", b-a}'; }
{
  echo "start: $(date -Iseconds)"
  echo "node: $(node --version) npm: $(npm --version)"
  t0=$EPOCHREALTIME
  npm ci --no-audit --no-fund 2>&1 | tail -5
  rc=${PIPESTATUS[0]}; t1=$EPOCHREALTIME
  echo "npm ci exit=$rc sec=$(el $t0 $t1)"
  t2=$EPOCHREALTIME
  npm run build 2>&1 | tail -25
  rc=${PIPESTATUS[0]}; t3=$EPOCHREALTIME
  echo "npm run build exit=$rc sec=$(el $t2 $t3)"
  echo "end: $(date -Iseconds)"
} > "$LOG" 2>&1
```

`sizes.sh`

```bash
#!/usr/bin/env bash
# 使い方: sizes.sh <dist ディレクトリ>
# dist 内の js/css/html の生バイト数と gzip -9 後のバイト数を一覧にする
DIR="$1"
find "$DIR" -type f \( -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.wasm' \) | sort | while read -r f; do
  raw=$(wc -c < "$f"); gz=$(gzip -9 -c "$f" | wc -c)
  printf "%s\t%s\t%s\n" "${f#$DIR/}" "$raw" "$gz"
done
```

`scaffold_bench.sh`

```bash
#!/usr/bin/env bash
# 使い方: scaffold_bench.sh <作業ディレクトリ>
# 比較用の雛形を作り、npm install とビルドの時間を測る（雛形の初期状態のまま。チャット画面ではない）
set -u
W="$1"; mkdir -p "$W"; cd "$W" || exit 1
el() { awk -v a="$1" -v b="$2" 'BEGIN{printf "%.1f", b-a}'; }
echo "start: $(date -Iseconds) node=$(node --version)"
for tpl in react-ts svelte-ts preact-ts; do
  t0=$EPOCHREALTIME
  npm create vite@9.3.3 "vite-$tpl" -- --template "$tpl" --no-interactive --no-immediate < /dev/null > "log-create-$tpl.txt" 2>&1
  (cd "vite-$tpl" && npm install --no-audit --no-fund > "../log-install-$tpl.txt" 2>&1); t1=$EPOCHREALTIME
  (cd "vite-$tpl" && npm run build > "../log-build-$tpl.txt" 2>&1); rc=$?; t2=$EPOCHREALTIME
  echo "$tpl create+install_sec=$(el $t0 $t1) build_sec=$(el $t1 $t2) build_exit=$rc"
done
# Next.js（App Router・静的書き出し）
t0=$EPOCHREALTIME
npx --yes create-next-app@16.4.4 next-app --ts --app --no-tailwind --eslint --no-src-dir --import-alias "@/*" --use-npm --no-turbopack --yes < /dev/null > log-create-next.txt 2>&1 || \
npx --yes create-next-app@16.4.4 next-app --ts --app --use-npm --yes < /dev/null > log-create-next2.txt 2>&1
t1=$EPOCHREALTIME
if [ -d next-app ]; then
  cat > next-app/next.config.ts <<'CFG'
import type { NextConfig } from "next";
const nextConfig: NextConfig = { output: "export" };
export default nextConfig;
CFG
  (cd next-app && npm run build > ../log-build-next.txt 2>&1); rc=$?; t2=$EPOCHREALTIME
  echo "next create+install_sec=$(el $t0 $t1) build_sec=$(el $t1 $t2) build_exit=$rc"
else
  echo "next scaffold failed"
fi
echo "end: $(date -Iseconds)"
```

## 付録 B: 生データ

`run1.log`（Q-a の npm ci と 1 回目の build）

```text
start: 2026-11-03T17:02:40+09:00
node: v24.13.1 npm: 11.8.0
npm notice
npm notice New minor version of npm available! 11.8.0 -> 11.21.1
npm notice Changelog: https://github.com/npm/cli/releases/tag/v11.21.1
npm notice To update run: npm install -g npm@11.21.1
npm notice
npm ci exit=0 sec=41.8

> app@0.0.0 build
> tsc -b && vite build

vite v8.0.16 building client environment for production...
transforming...✓ 30 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.30 kB
dist/assets/hero-CLDdwZDr.png    13.05 kB
dist/assets/index-D64VDMd1.css    4.10 kB │ gzip:  1.47 kB
dist/assets/index-pImcdjAf.js   252.20 kB │ gzip: 76.99 kB

✓ built in 920ms
npm run build exit=0 sec=15.0
end: 2026-11-03T17:03:40+09:00
```

`build_run2.log`・`build_run3.log`（2・3 回目の build）は、先頭の空行と `built in` の行を除いて 1 回目の build の部分と同じ（`diff` で確かめた）。違う行は 2 回目 `✓ built in 424ms`、3 回目 `✓ built in 829ms`。

`sizes_regenerated.tsv`（gzip 後の大きさ。9 節のとおり 17:48 に計算し直したもの）

```text
# sizes.sh を、11/3 17:04〜17:08 に作られて残っていたビルド成果物（dist）に 2026-11-03T17:48:22+09:00 にもう一度かけた出力。元の実行の出力はファイルに残していなかった。gzip: gzip 1.14
condition	file	raw_bytes	gzip9_bytes
current/frontend	assets/index-D64VDMd1.css	4105	1489
current/frontend	assets/index-pImcdjAf.js	252203	75688
current/frontend	index.html	466	309
scaffold/vite-react-ts	assets/index-D64VDMd1.css	4105	1489
scaffold/vite-react-ts	assets/index-GpEN3EET.js	222447	68374
scaffold/vite-react-ts	index.html	463	308
scaffold/vite-svelte-ts	assets/index-C6Y0TU_e.js	30766	12241
scaffold/vite-svelte-ts	assets/index-CsUDhMuy.css	4104	1483
scaffold/vite-svelte-ts	index.html	463	306
scaffold/vite-preact-ts	assets/index-B_WqFTzy.js	18093	7379
scaffold/vite-preact-ts	assets/index-DiN-lbiA.css	4283	1497
scaffold/vite-preact-ts	index.html	463	307
```

`scaffold_summary.log`（Q-b。最後の行は `timeout 600` による打ち切り）

```text
start: 2026-11-03T17:05:51+09:00 node=v24.13.1
react-ts create+install_sec=42.5 build_sec=6.8 build_exit=0
svelte-ts create+install_sec=41.2 build_sec=13.6 build_exit=0
preact-ts create+install_sec=44.2 build_sec=14.5 build_exit=0
Terminated
```

`devserver_vs_preview.json`（Q-c）

```json
{
  "note": "Q-c の生データ。2026-11-03 17:17 頃 JST、Claude Code デスクトップの Browser ペインで各 URL を新しいタブで開き、2.5 秒待ってから Performance API の値をコンソールで集計したものをそのまま写した。対象は origin/main 14f8d57 の frontend を git archive したもの。",
  "dev": {
    "command": "npx vite --port 5199 --strictPort --host 127.0.0.1",
    "url": "http://127.0.0.1:5199/",
    "requests_total": 25,
    "js_like_requests": 23,
    "transfer_bytes_total": 1697392,
    "decoded_bytes_total": 1689892,
    "decoded_bytes_js": 1676212,
    "load_event_ms": 537,
    "top5_decoded": [
      ["/node_modules/.vite/deps/react-dom_client.js?v=192cef49", 820919],
      ["/@vite/client", 209993],
      ["/node_modules/.vite/deps/react-router-dom.js?v=8a94be14", 201230],
      ["/@react-refresh", 111894],
      ["/src/components/McpAgentTest.tsx", 56867]
    ]
  },
  "preview": {
    "command": "npx vite preview --port 5198 --strictPort --host 127.0.0.1",
    "url": "http://127.0.0.1:5198/",
    "requests_total": 4,
    "js_requests": 1,
    "transfer_bytes_total": 92366,
    "decoded_bytes_total": 269831,
    "decoded_bytes_js": 252203,
    "load_event_ms": 379,
    "all": [
      ["/assets/index-pImcdjAf.js", 76470, 252203],
      ["/assets/index-D64VDMd1.css", 1773, 4105],
      ["/assets/hero-CLDdwZDr.png", 13357, 13057]
    ]
  },
  "js_snippet": "const nav=performance.getEntriesByType('navigation')[0]; const res=performance.getEntriesByType('resource'); const sum=(a,k)=>a.reduce((s,e)=>s+(e[k]||0),0); ({requests_total:res.length+1, transfer_bytes_total:sum(res,'transferSize')+nav.transferSize, decoded_bytes_total:sum(res,'decodedBodySize')+nav.decodedBodySize})"
}
```

`all` の各行は [パス, 転送バイト, 展開後バイト]。

`gms_check.log`（Q-d の 2 回目。ホスト名を `$GMS_HOST` に置き換えた）

```text
run_at: 2026-11-03T17:21:32+09:00
== curl -sI http
HTTP/1.1 308 Permanent Redirect
Location: https://$GMS_HOST/
Date: Tue, 03 Nov 2026 08:21:32 GMT
Content-Length: 18

== cert
subject=CN=TRAEFIK DEFAULT CERT
issuer=CN=TRAEFIK DEFAULT CERT
notBefore=Nov  1 03:34:26 2026 GMT
notAfter=Nov  1 03:34:26 2027 GMT
== https / (insecure)
404 text/plain; charset=utf-8
== https /api/docs (insecure)
404 text/plain; charset=utf-8
== https / (verify)
000
exit=60
```

## 付録 C: 試行錯誤の経緯

| 時刻（JST） | したこと | 起きたこと | 対応 |
|---|---|---|---|
| 17:06 | Q-b を裏で流している間に、Q-d を 1 回目として確かめた | 8.4 と同じ結果。出力はファイルに残さなかった | 17:21:32 に同じ確認をもう一度流してファイルに残した（付録 B） |
| 17:08 頃〜17:15:51 | Q-b の Next.js | create-next-app の作成と install に約 7 分かかり、17:15:48 にビルドを始めた約 3 秒後に `timeout 600` で打ち切られた。`log-build-next.txt` は空 | 測り直していない（9 節） |
| 17:48 | gzip 後の大きさの出力が残っていないことに気づいた | — | 残っていたビルド成果物に `sizes.sh` をかけ直して保存した。値は表と一致（9 節） |
