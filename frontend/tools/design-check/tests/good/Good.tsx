import { House } from "@phosphor-icons/react";

export function PlanHeader() {
  // 見出しの帯 — 押したら時間割へ移る → 状態は保存しない 🚀
  return (
    <header
      className="bg-surface text-ink border-b border-rule"
      style={{ fontFamily: '"BIZ UDPGothic", sans-serif', transition: "background-color 120ms ease-out" }}
    >
      <House weight="bold" />
      <h2>今学期の時間割</h2>
    </header>
  );
}
