---
version: alpha
name: 禁止に当たらない DESIGN.md（テスト用）
colors:
  primary: "#0A7C86"
  surface: "#F2F5F3"
  ink: "#1C2422"
  subtle: "#5B6764"
typography:
  h1: { fontFamily: BIZ UDPGothic, fontSize: 28px, fontWeight: 700, lineHeight: 1.4 }
  body: { fontFamily: BIZ UDPGothic, fontSize: 16px, fontWeight: 400, lineHeight: 1.8 }
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
  body-text:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
  caption:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.subtle}"
---

## Overview

大学1年生が履修を組み立てるための画面。飾りより、科目の関係が読めることを優先する。

## Typography

本文も見出しも BIZ UDPGothic。Inter や Noto Sans JP は使わない（禁止リスト F01・F38）。 <!-- banlist:allow -->

## Colors

| 前景 | 背景 | 用途 |
| --- | --- | --- |
| ink | surface | 本文 |
| primary | surface | UI |
