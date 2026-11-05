# コースナビ デザインコンペ用の禁止リストと検証ツール

コースナビ（大学1年生向けの履修選択支援 AI。スマホと PC の日本語 Web アプリ）の DESIGN.md コンペで、審査を機械的に進めるための道具一式。依頼主の要望は「Claude などでよく使われるフォントやデザインは使わない。書体と色は、使う理由を検証してから採用する」。

このフォルダ（`frontend/tools/design-check/`）は、2026-11-03 のデザインシステム・コンペの作業フォルダから写したもの。コンペの経緯と結果は `docs/experiments/2026-11-03_frontend-design-competition.md`、確定したデザインシステムは `docs/frontend/DESIGN.md` にある。根拠の元データ（`_evidence/`）とフォントのファイルはリポに入れていない。

## ファイル

| ファイル | 役割 |
| --- | --- |
| `banlist.md` | 禁止リスト（人が読む版）。項目ごとに「なぜ禁止か」と根拠（URL かファイルパス:行） |
| `banlist.json` | 同じ内容の機械用データ。`check_banlist.py` が読む |
| `check_banlist.py` | CSS / HTML / TSX / Markdown から、禁止の書体・色・パターンを拾う |
| `check_contrast.py` | 色のペアの WCAG 2.2 コントラスト比を出し、AA を判定する |
| `check_font.py` | フォントファイルの日本語収録率・サイズ・ライセンス・x-height / cap-height を出す |
| `colorlib.py` | 色の読み取りと計算（上の2つが共有する。外部パッケージなし） |
| `specimen.html` | 候補の書体を 14・15・16px で並べる見本ページ（スクリーンショット用） |
| `tests/` | 違反を入れたサンプル（`bad/`）、違反の無いサンプル（`good/`）、コントラストの例（`contrast/`）、まとめて確かめる `run_tests.py` |
| `_evidence/`（リポには置いていない） | 根拠の元データ（anthropic.com / claude.com の CSS と抜き出し、依頼主の PC での書体の集計、色のしきい値の較正）。他社のサイトの CSS の写しを含むので、リポには入れていない。出典は `banlist.md` の2章 |

Python は `uv run` で動かす。外部パッケージは `--with` で一時的に入れ、グローバルには入れない。以下のコマンドはこのフォルダ（`frontend/tools/design-check/`）で実行する。`tests/run_tests.py` だけは、どのフォルダからでも動く。

## 各ツールの使い方

### check_banlist.py（禁止リスト）

```sh
uv run python check_banlist.py 応募者のフォルダ/            # フォルダ以下の css/scss/html/vue/astro/tsx/jsx/ts/js/md/mdx を全部
uv run python check_banlist.py DESIGN.md styles.css          # ファイルを指定
uv run python check_banlist.py --json DESIGN.md              # 機械向けの JSON
uv run python check_banlist.py --fail-on caution DESIGN.md   # 要注意でも終了コード 1
uv run python check_banlist.py --self-check                  # banlist.json と banlist.md の一致を確かめる
```

- 出力は `ファイル:行:列 [禁止|要注意] ID 種類: 名前` と詳細、最後に件数（禁止・要注意・許可）と ID 別の件数。
- 終了コード: 0 = 禁止なし、1 = 禁止あり、2 = 使い方やデータの誤り。
- 書体: `font-family`、`font` 一括指定、CSS 変数、`fontFamily`（JS と DESIGN.md の YAML）、Tailwind の `fontFamily` と `font-[…]`、md の表の「書体, serif」の形、Web フォントの読み込み（Google Fonts の URL、`next/font/google`、`@fontsource`、Fontshare、`@font-face`）、md の本文に書いた書体名を見る。「先頭のみ」の書体（Roboto・Arial・Helvetica・Georgia・Noto Sans JP）は代替の位置なら違反にしない。
- 色: hex・rgb()・hsl()・oklch()・oklab() を読み、禁止色の見本との色差 ΔE00 がしきい値以下なら違反。クリーム系と紫は OKLCH の色相の門も通ったものだけ。不透明度 0.5 未満の色は見ない。しきい値の決め方は `banlist.md` の4章。
- パターン: P01〜P27（`banlist.md` の5章）。コメントの中の文字（`/* */`、`<!-- -->`、`//`）は、画面に出る文字を見る検出（絵文字・中黒・→・em ダッシュ・番号）から外す。
- 行に `banlist:allow` と書くと、その行の検出は「許可」に回る。件数には数えないが一覧には必ず出るので、審査では許可の理由を確かめる。DESIGN.md で「Inter は使わない」と書く行などに使う。

### check_contrast.py（WCAG 2.2 コントラスト）

```sh
uv run --with pyyaml python check_contrast.py DESIGN.md      # frontmatter の components と、本文の「前景・背景・用途」の表
uv run python check_contrast.py tests/contrast/pairs.json    # JSON
uv run python check_contrast.py --pair "#5b6764" "#f2f5f3" --use 本文
```

- 基準: 本文 4.5:1、大きい文字（24px 以上か、18.66px 以上の太字）3:1、UI 部品（枠線・アイコン・フォーカス表示）3:1。比は丸めずに判定し（2.996 は 3:1 に不合格）、表示は小数2桁で切り捨てる。
- DESIGN.md の frontmatter は、`colors` をトークン、`components` の `textColor` と `backgroundColor` の組をペアにする。component の `typography` が大きい文字なら 3:1 で判定する。
- 本文の表は、見出しに「前景（fg）」「背景（bg）」があれば読み、「用途」列（本文 / 大きい文字 / UI）で基準を決める。
- 半透明の前景は背景に重ねて、半透明の背景は `--base`（既定 #ffffff）に重ねて計算し、その旨を出力に書く。
- 終了コード: 0 = 全部合格、1 = 不合格あり、2 = 入力の誤り（読めない色・未定義のトークン・ペアが1つも無い）。黙って通すことはしない。

### check_font.py（フォントファイル）

```sh
uv run --with fonttools --with brotli python check_font.py 候補.woff2 候補-Bold.woff2
uv run --with fonttools --with brotli python check_font.py --json 候補.ttf
```

- (a) JIS X 0208 の第1水準漢字（2965字）・第2水準漢字（3390字）・ひらがな（83字）・カタカナ（86字）・全角記号（1〜2区の147字）・全角英数（62字）の収録率と、欠けている字の例。文字の一覧は Python の codec（euc_jp と cp932）から作り、字数が規格どおりでなければ止まる。
- (b) ファイルサイズ・形式（WOFF2 / WOFF / TrueType / OpenType）・グリフ数・可変フォントの軸。
- (c) name テーブルの著作権・ライセンス説明・ライセンス URL・製造者など、OS/2 の埋め込み許可（fsType）。
- (d) x-height と cap-height。OS/2 の申告値と、x と H のグリフの実測値の両方と、その比（x/cap）。
- 終了コード: 0 = 全部読めた、2 = 読めないファイルがあった。

### specimen.html（スマホ幅の見本）

候補の書体で、コースナビに出そうな文（日付・時限・科目名・教員名の異体字・かな・記号・英数字・画数の多い字）を 14・15・16px、標準と太字で並べる。読み込みに失敗したら赤い枠で「この画面で判断しない」と出し、代わりの書体のまま並べることはしない。

```
specimen.html?font=フォントのURL&family=書体名&weight=400&width=375
```

- `font` は https の URL（Google Fonts の gstatic など、CORS を許す配信元）か、ページと同じサーバーのパス。手元のファイルは画面の「フォントファイルを選ぶ」から読める。
- 太字のファイルを読まない場合、太字の行はブラウザの擬似太字になる（上の枠にも出る）。太字も採用するなら太字のファイルで別に撮る。
- ヘッドレスの Chrome は窓を約 500px より狭くできないので、スマホ幅は `width=375` などで本文の幅を固定して撮る。

```sh
chrome --headless=new --hide-scrollbars --force-device-scale-factor=3 --window-size=420,2800 \
  --virtual-time-budget=8000 --screenshot=shots/候補名-375.png "file:///…/specimen.html?font=…&family=…&width=375"
```

### tests/run_tests.py（まとめて確かめる）

```sh
uv run --with fonttools --with brotli --with pyyaml python tests/run_tests.py <フォントのフォルダ>
```

引数にフォントのフォルダ（`BIZUDPGothic-Regular.ttf`、`AtkinsonHyperlegible-latin.woff2`、`NotoSansJP-subset-text.woff2`、`OFL-bizudpgothic.txt` を置いたもの）を渡すと `check_font.py` も確かめる。渡さなければその部分は飛ばし、飛ばしたことを表示する。

## 採用する前に通す検証の手順（コンペの審査フロー）

書体1つ・色1つごとに、次の順で通す。前の段で落ちたら先へ進まない。結果は応募の DESIGN.md の「採用理由と検証結果」の表に貼る（下に雛形）。

1. **禁止リストに当たらない**
   `uv run python check_banlist.py --fail-on ban 応募フォルダ/` で禁止が 0 件であること。要注意（F41〜F49、C06、P21〜P27）が出たら、DESIGN.md に「なぜそれでなければならないか」を書く。理由が無ければ差し戻す。`banlist:allow` の行は、許可の理由が書いてあるかを確かめる。目視の項目（`banlist.md` の M01〜M11）は審査者が画面で見る。

2. **日本語の収録率**
   `uv run --with fonttools --with brotli python check_font.py 候補ファイル` の (a) を見る。目安（依頼主が変えてよい）: 第1水準・ひらがな・カタカナ・全角記号・全角英数は 100%。第2水準は科目名や教員名に出るので 100% が望ましく、欠ける場合は欠けた字をどの書体で出すか（代替の書体指定）を DESIGN.md に書く。欧文書体を和文と混ぜる場合は、和文側の書体でこの段を通す。

3. **スマホの 14〜16px で撮って見る**
   `specimen.html` を幅 375px（iPhone 相当）と 360px（Android 相当）、倍率 3 で撮り、`shots/候補名-375.png` などで保存して DESIGN.md に貼る。見るところ: 画数の多い字（鬱・齟齬・薔薇）がつぶれないか、かなと漢字の大きさの釣り合い、英数字と混ぜたときの高さと間隔、I・l・1 と O・0 の見分け、太字が本物の太字か（擬似太字でないか）、行間 1.7 で詰まって見えないか。

4. **コントラスト**
   DESIGN.md の frontmatter の components（`textColor` と `backgroundColor`）か、「前景・背景・用途」の表に、使う組み合わせを全部書き、`uv run --with pyyaml python check_contrast.py DESIGN.md` で全部合格すること（本文 4.5:1、大きい文字と UI 部品 3:1）。

5. **配信サイズ**
   実際に配る形（woff2、サブセットや unicode-range で分けるならその全部）を `check_font.py` の (b) で測り、合計と、最初の画面に要る分を DESIGN.md に書く。参考に、BIZ UDPGothic の TTF 1本（JIS 第1・第2水準を全部含む）は 4,669,688 バイト（4.45 MB）だった（`tests/run_tests.py` で測った値）。システムフォントなら 0 バイト。**予算（何 KB までなら可か）はまだ決めていない。コンペの前に依頼主が決める。**

6. **ライセンス**
   `check_font.py` の (c) で、SIL OFL・Apache などの自由なライセンスか、埋め込み許可（fsType）がインストール可か、ライセンス URL を確かめて DESIGN.md に書く。有料の書体なら、使う権利を確かめた書類を添える。name テーブルにライセンスの記載が無い書体は、配布元のライセンス文書を確かめるまで採用しない。

### 「採用理由と検証結果」の雛形（応募の DESIGN.md に貼る）

| 対象 | 採用する理由（なぜこれか） | 1 禁止リスト | 2 収録率 | 3 14〜16px | 4 コントラスト | 5 配信サイズ | 6 ライセンス |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 本文の書体 ○○ | （コースナビの何に合うか） | 禁止 0・要注意 0 | 第1 100% / 第2 ○% | shots/○○-375.png | ─ | ○○ KB | OFL 1.1 |
| 文字色 #○○○○○○ / 地 #○○○○○○ | （なぜこの色か） | 禁止 0 | ─ | ─ | 本文 ○.○○:1 合格 | ─ | ─ |

## テストの結果（2026-11-03）

`tests/run_tests.py` で 24 項目すべて合格。

- `check_banlist.py`: 違反サンプル（`tests/bad/` の4ファイル）で禁止 72 件・要注意 15 件、終了コード 1。狙った 44 種の ID（色 C01〜C06、パターン P01〜P27、書体 11種）がすべて出て、狙っていない ID は出なかった。違反の無いサンプル（`tests/good/` の4ファイル）は禁止 0・要注意 0・許可 1（許可マーカーの行）、終了コード 0。Roboto と Noto Sans JP を代替に置いただけでは出ないこと、コメントの中の em ダッシュ・→・絵文字と `backdrop-filter: none` で出ないことも確かめた。md の区分を変えたり行を消したりすると `--self-check` が不一致を出す。
- `check_contrast.py`: 黒と白が 21:1、#767676 は本文合格（4.54）、#777777 は本文不合格（4.47）・大きい文字なら合格、#949494 は UI 合格（3.03）、#959595 は UI 不合格（2.99）、半透明の黒 50% は #808080 として計算（3.94）。DESIGN.md（違反なし）は5組とも合格、（違反あり）は2組とも不合格。未定義のトークンは終了コード 2。
- `check_font.py`: BIZ UDPGothic（TTF）は JIS X 0208 の全区分 100%・OFL・x/cap 0.720（実測）、Atkinson Hyperlegible の欧文 woff2 は漢字 0%・x/cap 0.743、「あいう亜ア」だけの Noto Sans JP サブセット woff2 はひらがな 3・カタカナ 1・第1水準 1、テキストファイルは終了コード 2。フォントは Google Fonts の公式配布元（github.com/google/fonts と fonts.gstatic.com）から作業フォルダの外に取った（リポには置いていない）。
- `specimen.html`: ヘッドレスの Chrome で BIZ UDPGothic（Google Fonts の text= サブセット）を 375px 幅・倍率 3 で撮れることと、存在しない URL では赤い枠の「読み込み失敗」が出ることを確かめた（`tests/shots/`）。

## 限界

- `check_font.py` は OpenType（CFF）の .otf と .ttc（コレクション）を試していない（.ttc は先頭の1書体だけ読む）。
- `check_banlist.py` の検出は正規表現と簡単な構文の読み取りで、CSS-in-JS の組み立てや変数経由の値（`var(--x)` の先の色や書体）までは追わない。見本から離れた「別の Claude らしい色」も拾えない。目視の項目と組み合わせる。
- md の本文に書体名を書くと、否定文でも違反として拾う（許可マーカーで回す）。
- 禁止リストの根拠と限界は `banlist.md` の1章と8章。
