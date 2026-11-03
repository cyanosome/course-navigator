---
version: alpha
name: わざと禁止に当たる DESIGN.md
colors:
  primary: "#D97757"
  surface: "#F4F1EA"
  ink: "#1A1714"
  muted: "#B0AEA5"
typography:
  h1: { fontFamily: Instrument Serif, fontSize: 40px, fontWeight: 400, lineHeight: 1.1 }
  body: { fontFamily: Geist, fontSize: 16px, fontWeight: 400, lineHeight: 1.7 }
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
  caption:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.muted}"
---

## Overview

AI らしさを全部入れた悪い例。✨

## Typography

| 役割 | 書体 |
| --- | --- |
| 見出し | Shippori Mincho, serif |
| 本文 | "Noto Sans JP", sans-serif |
| 数字 | IBM Plex Mono |

## Components

- アイコンは lucide-react の既定セット
- 強調ボタンは `bg-violet-600 shadow-lg`
- ヘッダーは `backdrop-filter: blur(8px)` のすりガラス
