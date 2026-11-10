# 禁止リスト（コースナビ DESIGN.md コンペ用）

- 版: 2026-11-03
- 機械用のデータ: 同じフォルダの `banlist.json`（中身は同じ）。`check_banlist.py --self-check` で、この md の表と JSON の ID・区分・しきい値・色が一致することを確かめる。
- 依頼主の要望: Claude などでよく使われるフォントやデザインは、Claude らしさが前に出るので使わない。採用する書体と色は、理由を検証してから決める。

## 1. 何を根拠にし、どう区分したか

**禁止**にしたのは、次のどれかに当たるものだけ。

1. Anthropic / Claude のブランドの資産（Anthropic の公式スキルか、anthropic.com・claude.com の実際の CSS で確かめたもの）
2. 「AI / LLM の既定」「AI 生成の特徴」と名指しした資料が1つ以上ある
3. Anthropic が Claude に「これを使え」と渡している書体（Claude Cookbook の公式プロンプトの推奨一覧）。Claude らしさの直接の出どころなので禁止に入れた
4. このPCの過去の成果物で、Claude 共著のコミットがある別々の成果物2つ以上で、主書体に選ばれている

**要注意**（採用するなら特に強い理由が要る）は、次のどちらか。

- 反 AI スロップ系のスキル2つ以上が「代わりに」勧めているが、AI の癖と名指しした根拠は無い（AI が次に集まる先）
- このPCでの使用が1件だけ

**根拠なし**: 候補に挙がったが上のどれにも当たらなかったもの。禁止にはしない（7章）。

hallmark・taste-skill・ui-ux-pro-max は第三者が書いたスキルで、中身は意見。ただし AI が読んで従う指示なので、AI が何を選ぶかの根拠としては直接効く。

## 2. 根拠の一覧

種類が「ローカル」の出典は、禁止リストを作った依頼主の PC にあるファイル（`~` はホームフォルダ）。リポには写しを置いていない。

| ID | 種類 | 出典 | 中身 |
| --- | --- | --- | --- |
| E01 | Web | [Claude Cookbook: Prompting for frontend aesthetics](https://platform.claude.com/cookbook/coding-prompting-for-frontend-aesthetics)（Anthropic, 2025-10-21） | Claude 向けの公式プロンプト。Inter / Roboto / Open Sans / Lato / 既定のシステムフォントを「使うな」と並べる。代わりの推奨に JetBrains Mono・Fira Code・Space Grotesk・Playfair Display・Crimson Pro・Fraunces・Clash Display・Satoshi・Cabinet Grotesk・IBM Plex family・Source Sans 3・Bricolage Grotesque・Obviously・Newsreader。Claude は Space Grotesk に収束しがちと書く。白背景の紫グラデーションを陳腐と名指し。背景にグラデーションを重ねることを勧める |
| E02 | ローカル | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/frontend-design/skills/frontend-design/SKILL.md:17,25-28,30,32,38-45`（作者 Anthropic、v1.1.1） | AI 生成デザインの集まりどころ5つ。39行: クリーム背景（#F4F1EA 付近）＋高コントラストのセリフ見出し＋テラコッタ（#D97757 付近。Anthropic 自身の Claude のアクセント色と明記）。42行: 同じ角丸カードに同じ rgba(0,0,0,.1) の影、装飾のグラデーション。43行: 大文字＋字間の eyebrow、中黒でつないだメタ情報、空白つき em ダッシュ、#111 などの色付きの黒、小さなラベルに等幅、末尾の →。26行: 見出しの一語だけ斜体。30行: 01/02/03 の番号。32行: セクションごとのフェード＋スライドアップ |
| E03 | ローカル | `~/.gemini/config/skills/frontend-design/SKILL.md:30,34,36,38`（Anthropic の旧版、Apache-2.0） | Arial と Inter を避ける（30行）。グラデーションメッシュ・ノイズ・グレインを勧める（34行）。Inter, Roboto, Arial, system fonts と白背景の紫グラデーションを名指し（36行）。Space Grotesk に収束するな（38行） |
| E04 | ローカル | `~/.claude/skills/synced/<同期 ID>/brand-guidelines/SKILL.md:21-24,28-30,34-35`（Anthropic 公式） | Anthropic のブランド色: Dark #141413、Light #faf9f5、Mid Gray #b0aea5、Light Gray #e8e6dc、Orange #d97757、Blue #6a9bcc、Green #788c5d。見出し Poppins（代替 Arial）、本文 Lora（代替 Georgia） |
| E05 | ローカル（Web から取得） | `_evidence\anthropic_css_extract.txt:9-19,24-33,37-47,66-72,75-96,101-109,131-138`（https://www.anthropic.com/ と https://claude.com/ のトップページが読む CSS を 2026-11-03 に取得して抜き出し。元の CSS も `_evidence\` に保存）。原本の写しはリポに置いていない（他社のサイトの CSS の写しを含むため） | 書体: anthropicSans / anthropicSerif / anthropicMono、--styrene-b、--copernicus、--tiempos-text、--jetbrains-mono、Lato。色: clay #d97757・#c6613f・#c46849、gray-050 #faf9f5・100 #f5f4ed・150 #f0eee6・200 #e8e6dc、oat #e3dacc、sky #6a9bcc、olive #788c5d。E04 の7色はすべて anthropic.com の CSS に実在（131-138行） |
| E06 | ローカル | `~/.agents/skills/hallmark/references/anti-patterns.md:11-15,17-21,23-33,35-57,75-97,133-153,169-173,187-199,209-231,271-287,337-341` | AI 生成 UI の名指しの特徴: 紫グラデーションのヒーロー、Inter だらけ、3列カード、カードの入れ子、グラデーション文字、片側の太い色帯、100vh 中央寄せヒーロー、オーロラ背景、見出しの一語斜体、全セクションの eyebrow、目的のないすりガラス、絵文字アイコン、transition-all、一律 hover:scale-105、バウンスするイージング、スクロールのたびのフェードアップ |
| E07 | ローカル | `~/.agents/skills/hallmark/references/typography.md:36-44,54-109,136,234-243` | 36-44行: LLM の既定として禁止する書体（Inter, Roboto, Open Sans, Lato, Poppins, Source Sans, Nunito, Montserrat, Raleway, Work Sans, DM Sans, system-ui, Arial, Helvetica / Merriweather, Playfair Display, Lora, Source Serif, Georgia）。54-109行・136行: 代わりに勧める書体（＝このスキルを使う AI が次に集まる先）。75行: Outfit は既定として禁止。89行: Geist を「既定の本文サンセリフ」と呼ぶ |
| E08 | ローカル | `~/.agents/skills/hallmark/references/color.md:3,73-83` | 紫〜シアン、紫〜青、オレンジ〜ピンクのグラデーションを「どの LLM も選ぶ」と名指し |
| E09 | ローカル | `~/.agents/skills/hallmark/references/slop-test.md:30-31,35,45-47,76` | 不合格の関門: 表示書体が Inter 等、紫系グラデーション（background-clip:text を含む）、transition-all、一律 hover 拡大、オーバーシュート、絵文字アイコン |
| E10 | ローカル | `~/.agents/skills/hallmark/references/assets.md:49,61` | Lucide を「モダン SaaS の既定、2026 年の基準線」と書く。絵文字をアイコンにしない |
| E11 | ローカル | `third-party/taste-skill/SKILL.md:39,142,147-148,168-181,187,192-196,253,603,623,627,639,645,649`（依頼主の設定リポにある写し） | 「AI 紫グラデーション」「汎用グラスモーフィズム」「Inter + slate-900」を LLM の既定と名指し（39行）。lucide-react は非推奨（142・623行）。Fraunces と Instrument Serif を「LLM お気に入りの2大セリフ」として既定禁止（180行）。クリーム背景・真鍮/クレイ/オックスブラッド/黄土・エスプレッソ文字を hex で禁止（192-196行）。shadcn/ui を既定状態のまま出さない（627行）。eyebrow・中黒・em ダッシュ（253・645・649行） |
| E12 | ローカル | `~/.gemini/config/skills/ui-ux-pro-max/data/typography.csv:2-19,21,23,30,32,34,40,42-45,51,55-57` | AI に渡される書体の組み合わせ表。日本語は 23行の Noto Serif JP + Noto Sans JP の1組だけ |
| E13 | ローカル | `~/.gemini/config/skills/ui-ux-pro-max/SKILL.md:80,286,323-324` と `data/icons.csv:2-16` | 絵文字をアイコンにしない。アイコン表の既定がすべて lucide-react |
| E14 | ローカル（集計） | `_evidence\tally_local_fonts_primary.txt:1-17,27-50,54-55`（`_evidence\tally_local_fonts.py --primary` の出力）。原本の写しはリポに置いていない（依頼主の PC のファイルの集計のため） | このPCの Projects（vault 含む）の CSS/HTML/TSX で主書体に置かれた書体の数。Noto Sans JP 10件（Claude 共著5件、コースナビ資料2件を含む）、IBM Plex Mono 5件（全件 Claude 共著、コースナビ資料2件を含む）、Zen Kaku Gothic New 3件（全件 Claude 共著、うち2件は同じページの複製）、Shippori Mincho 2件（コースナビ資料、Claude 共著）、Outfit 2件（Claude 共著）。明朝見出し＋ゴシック本文もコースナビ資料と vsearch 紹介ページで Claude が選んでいる |
| E15 | Web | [Why Your AI Keeps Building the Same Purple Gradient Website](https://prg.sh/ramblings/Why-Your-AI-Keeps-Building-the-Same-Purple-Gradient-Website)（prg.sh, 2025-10-26） | AI の見た目として Inter/Roboto、紫/インディゴのアクセント、白背景の紫グラデーション、何にでも角丸、不透明度 0.1 の薄い影を挙げる。Tailwind 作者が 2025年8月に、Tailwind UI のボタンを bg-indigo-500 にしたことを冗談で謝った件を紹介 |
| E16 | Web | Tailwind CSS [v3.4.17 colors.js L224-257](https://github.com/tailwindlabs/tailwindcss/blob/v3.4.17/src/public/colors.js#L224-L257) / [v4.1.0 theme.css L147-172](https://github.com/tailwindlabs/tailwindcss/blob/v4.1.0/packages/tailwindcss/theme.css#L147-L172) | indigo-500 #6366f1・600 #4f46e5、violet-500 #8b5cf6・600 #7c3aed、purple-500 #a855f7・600 #9333ea。v4 は oklch 値 |
| E17 | Web | [create-next-app のテンプレート layout.tsx L2-13](https://github.com/vercel/next.js/blob/canary/packages/create-next-app/templates/app-tw/ts/app/layout.tsx#L2-L13) | 新規 Next.js アプリの既定書体が Geist と Geist Mono。このPCの `_archive\sandbox\modern-next-app\src\app\layout.tsx:2` も同じ |
| E18 | Web＋ローカル | [shadcn/ui Theming](https://ui.shadcn.com/docs/theming) と 依頼主の別のプロジェクトの `components.json:9,13` | 既定の --radius 0.625rem、--primary oklch(0.205 0 0)、--foreground oklch(0.145 0 0) など彩度ゼロの neutral。このPCの shadcn 初期化結果は baseColor neutral・iconLibrary lucide |
| E19 | Web | [The AI-Sparkles Icon Problem](https://www.nngroup.com/articles/ai-sparkles-icon-problem/)（Nielsen Norman Group, Kate Kaplan, 2024-09-20） | キラキラのアイコンが AI の事実上の記号になったと指摘 |

## 3. 書体

「判定の範囲」が **どこでも** の書体は、`font-family` の2番目以降（代替）に書いても違反。**先頭のみ** の書体は、主書体（先頭）に置いたときと Web フォントとして読み込んだときだけ違反で、OS の標準書体として代替に置くのは可。Web フォントの読み込み（Google Fonts の URL、`next/font/google`、`@fontsource`、Fontshare、`@font-face`）はどちらでも違反。DESIGN.md の本文に書体名を書いた場合も、**どこでも** の書体は違反として拾う（「使わない」と書く行には `banlist:allow` を付ける。許可した行も一覧には出る）。

### 3.1 欧文

| ID | 区分 | 書体 | 判定の範囲 | なぜ | 根拠 |
| --- | --- | --- | --- | --- | --- |
| F01 | 禁止 | Inter（Inter Tight / Inter Display / InterVariable を含む） | どこでも | AI 生成 UI の最頻出の既定。Anthropic 自身が Claude に「使うな」と書いている | E01 E03 E06 E07 E09 E11 E12 E15 |
| F02 | 禁止 | Roboto | 先頭のみ | Claude 公式プロンプトの「使うな」の筆頭。Android の標準書体なので代替は可 | E01 E03 E07 E15 |
| F03 | 禁止 | Open Sans | どこでも | Claude 公式プロンプトの「使うな」。LLM の既定 | E01 E07 E09 E12 |
| F04 | 禁止 | Lato | どこでも | Claude 公式プロンプトの「使うな」。anthropic.com 自体も読み込んでいる | E01 E05 E07 E09 E12 |
| F05 | 禁止 | Arial | 先頭のみ | Claude 向け資料が汎用書体として避けさせている。Anthropic ブランドの見出しの代替書体 | E01 E03 E04 E07 |
| F06 | 禁止 | Helvetica（Helvetica Neue を含む） | 先頭のみ | LLM の既定として名指し | E07 |
| F07 | 禁止 | Nunito | どこでも | LLM の既定として名指し | E07 E12 |
| F08 | 禁止 | Montserrat | どこでも | LLM の既定として名指し | E07 E12 |
| F09 | 禁止 | Raleway | どこでも | LLM の既定として名指し | E07 E12 |
| F10 | 禁止 | Work Sans | どこでも | LLM の既定として名指し | E07 E12 |
| F11 | 禁止 | Source Sans（3 / Pro） | どこでも | LLM の既定として名指しされ、同時に Claude 公式プロンプトの推奨にも入っている | E01 E07 E12 |
| F12 | 禁止 | Source Serif（4 / Pro） | どこでも | LLM の既定として名指し | E07 |
| F13 | 禁止 | Merriweather | どこでも | LLM の既定として名指し | E07 E12 |
| F14 | 禁止 | DM Sans | どこでも | LLM の既定として名指し。AI 向け組み合わせ表の「Tech Startup」の本文 | E07 E12 |
| F15 | 禁止 | Space Grotesk | どこでも | Anthropic 自身が「Claude はここに収束しがち」と書いている | E01 E03 E12 |
| F16 | 禁止 | Geist / Geist Mono | どこでも | create-next-app の既定書体。反 AI スロップ系スキルも「既定の本文サンセリフ」「Inter の代わり」として真っ先に勧める | E07 E11 E17 |
| F17 | 禁止 | Fraunces | どこでも | 「LLM お気に入りの2大セリフ」の片方。Claude 公式プロンプトの推奨 | E01 E07 E11 |
| F18 | 禁止 | Instrument Serif | どこでも | 「LLM お気に入りの2大セリフ」のもう片方 | E07 E11 |
| F19 | 禁止 | Playfair Display | どこでも | Claude 公式プロンプトの推奨。本文用としては使い古しと名指し。AI 向け組み合わせ表の先頭 | E01 E07 E12 |
| F20 | 禁止 | IBM Plex 系（Sans / Serif / Mono / Sans JP ほか全部） | どこでも | Claude 公式プロンプトの推奨（IBM Plex family）。このPCでは IBM Plex Mono が Claude 共著の成果物5件（コースナビ資料2件を含む）で使われている | E01 E07 E11 E12 E14 |
| F21 | 禁止 | JetBrains Mono | どこでも | Claude 公式プロンプトの推奨。anthropic.com も使っている | E01 E05 E07 E11 E12 |
| F22 | 禁止 | Fira Code | どこでも | Claude 公式プロンプトの推奨 | E01 E12 |
| F23 | 禁止 | Crimson Pro | どこでも | Claude 公式プロンプトの推奨 | E01 E07 E12 |
| F24 | 禁止 | Clash Display | どこでも | Claude 公式プロンプトの推奨 | E01 E07 E12 |
| F25 | 禁止 | Satoshi | どこでも | Claude 公式プロンプトの推奨。他のスキルも Inter の代わりに勧める | E01 E07 E11 E12 |
| F26 | 禁止 | Cabinet Grotesk | どこでも | Claude 公式プロンプトの推奨 | E01 E07 E11 |
| F27 | 禁止 | Bricolage Grotesque | どこでも | Claude 公式プロンプトの推奨 | E01 E07 |
| F28 | 禁止 | Obviously | どこでも | Claude 公式プロンプトの推奨 | E01 |
| F29 | 禁止 | Newsreader | どこでも | Claude 公式プロンプトの推奨 | E01 E07 E12 |
| F30 | 禁止 | Outfit | どこでも | 「既定としては禁止」と名指し。このPCでも Claude 共著の成果物2件で使われている | E07 E11 E12 E14 |

### 3.2 Anthropic / Claude のブランド由来

| ID | 区分 | 書体 | 判定の範囲 | なぜ | 根拠 |
| --- | --- | --- | --- | --- | --- |
| F31 | 禁止 | Anthropic Sans / Anthropic Serif / Anthropic Mono | どこでも | anthropic.com と claude.com が今使っている Anthropic の専用書体 | E05 |
| F32 | 禁止 | Styrene（A / B） | どこでも | anthropic.com の CSS に --styrene-b として残る | E05 |
| F33 | 禁止 | Tiempos（Text / Headline） | どこでも | anthropic.com の CSS に --tiempos-text として残る | E05 |
| F34 | 禁止 | Copernicus | どこでも | anthropic.com の CSS に --copernicus として残る | E05 |
| F35 | 禁止 | Poppins | どこでも | Anthropic 公式ブランドスキルの見出し書体。LLM の既定としても名指し | E04 E07 E09 E12 |
| F36 | 禁止 | Lora | どこでも | Anthropic 公式ブランドスキルの本文書体。LLM の既定としても名指し | E04 E07 E12 |
| F37 | 禁止 | Georgia | 先頭のみ | Anthropic ブランドの本文の代替書体で、claude.com のセリフの代替にも入っている。「Georgia を既定に」は LLM の癖と名指し | E04 E05 E07 |

### 3.3 和文

| ID | 区分 | 書体 | 判定の範囲 | なぜ | 根拠 |
| --- | --- | --- | --- | --- | --- |
| F38 | 禁止 | Noto Sans JP（同じデザインの Source Han Sans / 源ノ角ゴシック / Noto Sans CJK JP を含む） | 先頭のみ | このPCで Claude が日本語の主書体に最も多く選んだ（コースナビの過去資料を含む）。AI 向け組み合わせ表の日本語はこれ1組だけ。Android の標準書体と同じデザインなので代替は可 | E12 E14 |
| F39 | 禁止 | Shippori Mincho（B1 を含む） | どこでも | コースナビの過去資料2件（Claude 共著）で Claude が選んだ見出し書体そのもの | E14 |
| F40 | 禁止 | Zen Kaku Gothic New | どこでも | このPCで Claude 共著の別々の成果物2つ（vsearch 紹介ページ、個人サイト）で選ばれた | E14 |

### 3.4 要注意（採用するなら強い理由が要る）

| ID | 区分 | 書体 | 判定の範囲 | なぜ | 根拠 |
| --- | --- | --- | --- | --- | --- |
| F41 | 要注意 | Plus Jakarta Sans | どこでも | AI 向けの書体表2つで推奨（AI が次に選びやすい）。AI の癖と名指しした根拠は無い | E07 E12 |
| F42 | 要注意 | General Sans | どこでも | 反 AI スロップ系スキル2つが代わりに勧める | E07 E12 |
| F43 | 要注意 | EB Garamond | どこでも | 3つのスキルが代わりのセリフとして勧める | E07 E11 E12 |
| F44 | 要注意 | Cormorant / Cormorant Garamond | どこでも | 3つのスキルが代わりのセリフとして勧める | E07 E11 E12 |
| F45 | 要注意 | Bodoni Moda | どこでも | 2つのスキルが勧める | E07 E12 |
| F46 | 要注意 | Space Mono | どこでも | 2つのスキルが勧める | E07 E12 |
| F47 | 要注意 | Noto Serif JP（同じデザインの Source Han Serif / 源ノ明朝を含む） | どこでも | AI 向け組み合わせ表の日本語の見出し書体。このPCでの実使用は見つからなかった | E12 |
| F48 | 要注意 | Zen Old Mincho | どこでも | このPCの Claude 共著の成果物1つ（複製を除く）で見出しに使われた。1件なので禁止まではしない | E14 |
| F49 | 要注意 | M PLUS Rounded 1c | どこでも | このPCの1プロジェクトで使われ、Claude 共著は1件だけ | E14 |

## 4. 色

色差は **CIEDE2000（ΔE00）**。sRGB を CIELAB（D65）に直して、各グループの見本の色のうち一番近いものとの差を測り、しきい値以下なら当たり。CSS の hex・rgb()・hsl()・oklch()・oklab() を読む（Tailwind v4 の oklch 値も拾う）。不透明度 0.5 未満の色（影や薄い重ね）は色の判定から外し、影は P10 で見る。

ΔE00 だけでは「中立の白 #fafafa」と「クリームの #faf9f5」の差が 2.02 しかなく、しきい値で分けられない。そこで、似た色がありふれているグループには **色相の門**（OKLCH の色相・彩度・明度の範囲）を足し、門を通った色だけを ΔE00 で判定する。紫は CIELAB の色相が青と近く出るので、門は色相の分かれやすい OKLCH で引いた。

| ID | 区分 | 名前 | 見本の色 | しきい値 ΔE00 | 色相の門（OKLCH） | なぜ | 根拠 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | 禁止 | Claude のテラコッタ（clay） | #d97757 / #c6613f / #c46849 | 6.0 | なし | Anthropic の公式アクセント色で Claude の画面のアクセント。Anthropic の公式スキル自身が AI 生成デザインの典型と書く | E02 E04 E05 |
| C02 | 禁止 | Anthropic の暖色グレー／クリーム・アイボリー系の背景 | #faf9f5 / #f5f4ed / #f0eee6 / #e8e6dc / #e3dacc / #f4f1ea / #f5f1ea / #f7f5f1 / #fbf8f1 / #efeae0 / #ece6db / #faf7f1 / #e8dfcb | 5.0 | 色相 60〜115°・彩度 0.004 以上・明度 0.85 以上 | Claude の画面と Anthropic サイトの地の色。AI 生成デザインの典型（クリーム背景）とも名指し | E02 E04 E05 E11 |
| C03 | 禁止 | Anthropic の補助アクセント（sky / olive） | #6a9bcc / #788c5d | 3.0 | なし | Anthropic 公式ブランドの第2・第3アクセント。青と緑はありふれた色なので、しきい値を狭くしてほぼ同じ色だけを止める | E04 E05 |
| C04 | 禁止 | AI の紫（Tailwind indigo / violet / purple の 500・600） | #6366f1 / #4f46e5 / #8b5cf6 / #7c3aed / #a855f7 / #9333ea | 8.0 | 色相 268〜330°・彩度 0.10 以上 | AI 生成 UI の紫。Tailwind の既定 indigo が出どころと作者自身が認めている | E01 E03 E06 E08 E11 E15 E16 |
| C05 | 禁止 | AI の「高級消費財」パレット（真鍮・クレイ・オックスブラッド・黄土） | #b08947 / #b6553a / #9a2436 / #9c6e2a / #bc7c3a / #7d5621 | 4.0 | なし | LLM の既定として hex で名指しされたアクセント群 | E11 |
| C06 | 要注意 | 暖色寄りのほぼ黒（エスプレッソ）と Anthropic の Dark / Mid Gray | #141413 / #1a1714 / #1a1814 / #1b1814 / #b0aea5 | 3.0 | 色相 40〜115°・彩度 0.0015 以上 | Anthropic の文字色と LLM の既定と名指しされた文字色。ほぼ黒は誰でも使うので禁止にせず、クリーム背景やテラコッタと組むと Claude 配色になる目印として報告する | E04 E05 E11 |

### 4.1 しきい値の較正（抜粋）

元データは `_evidence\calibrate_colors.txt`（`_evidence\calibrate_colors.py` の出力。よく使われる参照色が当たるかどうか）。原本の写しはリポに置いていない。

| 参照色 | 一番近い見本 | ΔE00 | 判定 | 意図 |
| --- | --- | --- | --- | --- |
| #ffffff / #fafafa / #f5f5f5 | C02 | 2.35 / 2.02 / 2.06 | 当たらない（門を通らない） | 中立の白は止めない |
| #f8fafc / #f1f5f9 / #f2f5f3 | C02 | 3.13 / 4.37 / 2.19 | 当たらない（門を通らない） | 寒色寄りの白は止めない |
| #fffdf7 / #faf8f5 / #fff7ed / #fdf6e3 | C02 | 1.14 / 0.81 / 2.36 / 4.28 | 禁止 | クリーム寄りの白は止める |
| #fff8e1 / #fef3c7 | C02 | 5.44 / 8.26 | 当たらない | 黄色がはっきりした色は別物として通す |
| #da7756 / #c15f3c / #e07a5f / #cc785c / #e76f51 / #e2725b | C01 | 0.32〜3.65 | 禁止 | テラコッタの言い換えは止める |
| #ff7f50（coral）/ #ff6347（tomato）/ #ea580c / #f97316 / #ef4444 | C01 | 7.43 / 7.62 / 8.93 / 11.49 / 10.84 | 当たらない | 普通のオレンジ・赤は通す |
| #615fff / #aa3bff / #4338ca / #7e22ce | C04 | 2.47 / 4.19 / 5.45 / 6.09 | 禁止 | v4 の indigo、Vite の雛形の紫、indigo-700 などは止める |
| #2563eb / #1d4ed8 | C04 | 6.94 / 5.90 | 当たらない（門を通らない） | 青は止めない（ΔE00 だけだと近く出る） |
| #c084fc / #d946ef | C04 | 11.81 / 8.51 | 当たらない | 薄い紫・マゼンタは単色では通す（グラデーションに入れば P03） |
| #5b9bd5 / #7aa7d9 / #4a90e2 | C03 | 2.29 / 3.97 / 4.80 | 禁止 / 当たらない / 当たらない | sky とほぼ同じ色だけ止める |
| #1c1917（Tailwind stone-900） | C06 | 0.89 | 要注意 | 暖色のほぼ黒は報告する |
| #111111 / #1a1a1a / #18181b / #1c2422 | C06 | 1.00 / 1.95 / 3.27 / 6.76 | 当たらない | 中立・寒色のほぼ黒は報告しない |

## 5. 見た目のパターン

| ID | 区分 | パターン | 機械で拾うもの | なぜ | 根拠 |
| --- | --- | --- | --- | --- | --- |
| P01 | 禁止 | グラスモーフィズム | `backdrop-filter`（none 以外）、`backdropFilter`、Tailwind の `backdrop-blur-*` など | 目的のないすりガラスは AI 生成 UI の特徴として名指し | E06 E11 |
| P02 | 禁止 | グラデーション文字 | 同じ指定の中の `background-clip: text` と `gradient(`、`bg-clip-text` と `bg-gradient-to-*` / `from-*` の同居 | 「何より速く AI 生成と分かる」と名指し | E06 E07 E09 E11 |
| P03 | 禁止 | 紫系のグラデーション | gradient の色に OKLCH 色相 268〜330°・彩度 0.10 以上の色がある、Tailwind の `from-*` `via-*` `to-*` の indigo・violet・purple・fuchsia | AI 生成 UI の最もよく知られた見た目 | E01 E03 E06 E08 E09 E11 E15 |
| P04 | 禁止 | オレンジ→ピンクのグラデーション | gradient にオレンジ（色相 35〜80°）とピンク（330°超か 20°未満）の両方、Tailwind の `from-orange-*` と `to-pink-*` など | 「どの LLM も選ぶ」グラデーションとして名指し | E08 |
| P05 | 禁止 | Tailwind の indigo / violet / purple | `bg-indigo-500` `text-violet-600` `hover:bg-purple-500` など、`var(--color-indigo-*)` | AI の紫の出どころそのもの | E11 E15 E16 |
| P06 | 禁止 | 絵文字 | 絵文字の文字（✨🚀⚡🔥🎯✅ など。※ ○ ★ のような記号は対象外） | 絵文字をアイコンや飾りに使うのは AI の既定として名指し | E06 E09 E11 E13 |
| P07 | 禁止 | キラキラ（Sparkles）アイコン | `Sparkles` `AutoAwesome` `auto_awesome` `LuSparkles` `ph-sparkle` など | AI の事実上の記号。AI のアプリで使うと AI らしさが前に出る | E06 E19 |
| P08 | 禁止 | lucide アイコン | `lucide-react` などの import、lucide の CDN、`data-lucide`、md に lucide と書く | AI と shadcn/ui の既定のアイコンセット | E10 E11 E13 E18 |
| P09 | 禁止 | shadcn/ui の既定トークンのまま | `--radius: 0.625rem`、`oklch(0.205 0 0)`、`oklch(0.145 0 0)` | 「shadcn/ui を既定状態で出さない」と名指し | E11 E18 |
| P10 | 禁止 | 薄い黒の柔らかい影 | ほぼ黒・不透明度 0.03〜0.2・ぼかし 4px 以上の `box-shadow`、Tailwind の `shadow` `shadow-sm`〜`shadow-2xl` | 同じカードに同じ rgba(0,0,0,.1) の影、を AI 生成の典型と名指し。Tailwind の既定の影はこの値 | E02 E15 |
| P11 | 禁止 | 大文字＋広い字間の eyebrow | 同じ指定の `text-transform: uppercase` と 0.05em 以上の `letter-spacing`、`uppercase` と `tracking-wide` `tracking-wider` `tracking-widest` の同居 | AI のテンプレートの飾りとして名指し | E02 E06 E11 |
| P12 | 禁止 | 中黒（ · ）を2つ以上つないだメタ情報 | 1行に空白つきの「 · 」が2つ以上（和文の「・」は対象外） | AI のテンプレートの飾りとして名指し | E02 E11 |
| P13 | 禁止 | リンクやボタンの文字の末尾の → | 文字列やタグの直前の「→」、CSS の `content: "→"`（文中の「A → B」は対象外） | AI のテンプレートの飾りとして名指し | E02 |
| P14 | 禁止 | 前後に空白のある em ダッシュ | 「単語 — 説明」の形 | AI のテンプレートの飾りとして名指し | E02 E11 |
| P15 | 禁止 | 見出しの中の斜体 | `<h1>`〜`<h3>` の中の `<em>` `<i>`、見出しの `italic` クラス、見出し系セレクタの `font-style: italic` | 見出しの一語だけ斜体は AI の最も確かな癖の一つと名指し | E02 E06 |
| P16 | 禁止 | 片側だけ太い色帯のカード | `border-left: 3〜12px solid`、`border-l-4` など | AI 生成 UI の特徴として名指し | E06 |
| P17 | 禁止 | transition: all | `transition: all`、`transition-all` | AI の動きの癖として名指し | E06 E09 |
| P18 | 禁止 | 一律の hover 拡大 | `hover:scale-105` など、`:hover` での `scale(1.0x)`、`whileHover={{ scale: 1.05 }}` | AI の動きの癖として名指し | E06 E09 |
| P19 | 禁止 | 行き過ぎて戻るイージング | `cubic-bezier` の y が 0〜1 の外（例 `0.34, 1.56, 0.64, 1`）、Framer Motion の `ease: [...]` も同じ | AI の動きの癖として名指し | E06 E09 |
| P20 | 禁止 | セリフ（明朝）見出し＋サンセリフ（ゴシック）本文 | 同じファイルにセリフ系の書体指定とサンセリフ系の書体指定が両方ある（総称 serif / sans-serif、無ければ書体名の Mincho・Serif・Gothic・Sans などで判断） | 高コントラストのセリフ見出しは Anthropic のスキルが挙げる AI の典型。このPCでも Claude はコースナビ資料と vsearch 紹介ページで明朝見出し＋ゴシック本文を選んでいる | E02 E11 E14 |
| P21 | 要注意 | Tailwind 既定パレットのクラスをそのまま使う | `bg-slate-900` などの既定パレットのクラス（1行につき1件にまとめる） | 「Inter + slate-900」が LLM の既定と名指し | E11 E15 |
| P22 | 要注意 | 装飾のグラデーション背景 | P02〜P04 に当たらない gradient、`bg-gradient-to-*` | Claude 公式プロンプトがグラデーションを重ねることを勧め、Anthropic のスキル自身が装飾のグラデーションを AI の典型と書く | E01 E02 E03 |
| P23 | 要注意 | ノイズ・グレインの重ね | `feTurbulence`、`grain` `noise-overlay` などの名前 | Claude 向けの旧スキルが勧める装飾 | E03 |
| P24 | 要注意 | フェード＋スライドアップの登場 | 不透明度 0 から translate する `@keyframes`、`initial={{ opacity: 0, y: … }}` | セクションごとのフェードアップは AI 生成と読まれると名指し。1か所だけなら可 | E02 E06 |
| P25 | 要注意 | 画面いっぱいの高さ | `min-height: 100vh` など、`min-h-screen` `h-dvh` | 100vh の中央寄せヒーローは AI の既定と名指し。アプリの外枠などで要るなら理由を書く | E06 E09 |
| P26 | 要注意 | 01 / 02 のような番号ラベル | 「01 / 概要」「01 · 」の形 | 中身が本当に順序（手順など）でない限り AI の飾りと名指し | E02 E06 E11 |
| P27 | 要注意 | システムフォントだけの書体指定 | 書体指定の名前がすべて OS の標準書体（system-ui、Hiragino、Yu Gothic、Meiryo、Roboto など） | Claude 公式プロンプトは既定のシステムフォントを使うなと書く。和文は配信サイズの事情でシステムフォントが妥当なこともあるので、禁止ではなく理由を求める | E01 E03 E07 |

## 6. 目視で確認する項目（機械では拾わない）

| ID | 項目 | 根拠 |
| --- | --- | --- |
| M01 | 同じ幅の3列カード（アイコン→見出し→2行の本文） | E06 E11 |
| M02 | カードの中にカード | E06 |
| M03 | 何にでも同じ角丸（階層に関係なく1つの border-radius） | E02 E15 |
| M04 | 左ロゴ＋中央リンク＋右ボタンのナビ、4列リンクのフッター | E06 |
| M05 | 全部中央寄せ | E06 |
| M06 | 小さなデータラベルに等幅フォント | E02 |
| M07 | 黒に近い背景＋蛍光グリーンか朱色の1色アクセント | E02 |
| M08 | 新聞風（細い罫線・角丸ゼロ・段組み） | E02 |
| M09 | 大きな数字＋小さなラベル＋グラデーションのアクセントのヒーロー | E02 |
| M10 | CSS で描いたブラウザ枠・スマホ枠・ウィンドウの丸ボタン | E06 |
| M11 | 根拠のない数字（「3倍速い」「1万人が利用」など） | E06 |

## 7. 根拠が取れず、禁止にしなかった候補

| ID | 候補 | 禁止にしなかった理由 |
| --- | --- | --- |
| N01 | Manrope | AI 向けの書体表（ui-ux-pro-max typography.csv:19）で勧められているだけ。AI の癖と名指しした根拠も、このPCでの使用も、Web の根拠も見つからなかった |
| N02 | BIZ UDPGothic / BIZ UDGothic | このPCでは未コミットの資料1件と代替指定1件だけ。Claude が選んだと確かめられない |
| N03 | Zen Kaku Gothic Antique | 禁止の Zen Kaku Gothic New の姉妹書体だが、使われた根拠は無い |
| N04 | M PLUS 1p / Zen Maru Gothic / Kosugi Maru / Sawarabi Gothic / LINE Seed JP / Murecho | スキル・Web・このPCの過去成果物のどれにも、AI の既定としての根拠が出てこなかった |
| N05 | 純粋な黒 #000 と純粋な白 #fff | hallmark は禁止、Anthropic の frontend-design は逆に「色付きのほぼ黒」を AI の癖と書く。根拠が食い違うので禁止にしない |
| N06 | claude.ai アプリ本体の CSS の色と書体 | Cloudflare のチャレンジで取得できなかった（回避はしていない）。claude.com と anthropic.com の CSS で代用した |

## 8. 限界

- 「Claude 共著」は、そのファイルを触ったコミットの本文に `Co-Authored-By: Claude` があるという意味で、書体を選んだのが Claude だという証明ではない。vault のファイルは自動コミットでも共著が付く。
- Claude Cookbook の推奨一覧（E01）は「Claude にこれを使えと言っている」根拠で、世の AI 生成サイトでの実際の出現頻度は測っていない。
- Web の一般記事（E15）は個人ブログ。数字の裏付けは無い。
- 和文の「AI の既定」を名指しした Web の資料は見つからなかった。和文の禁止はこのPCでの実使用（E14）と AI 向け書体表（E12）だけが根拠。
- 色の判定は見本との色差なので、見本から離れた「別の Claude らしい色」は拾えない。目視（6章）と組み合わせる。
