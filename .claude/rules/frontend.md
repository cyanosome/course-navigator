---
paths: ["frontend/**"]
---

# frontend 運用ルール

- React 19 + Vite + TypeScript。コンポーネントは `src/components/` に `PascalCase.tsx` で配置。
- API 呼び出しは `fetch` で `/api/...` を叩く（Traefik がプレフィックスを剥がす前提）。
- 状態管理は基本 `useState`/`useEffect`。エラーは握りつぶさず `catch` 内で最低限 `console.error` する。
- 型は `interface` で明示し、`any` は使わない（`err: any` のような既存箇所も段階的に是正）。
- コミット前に `npm run lint` と `npx tsc --noEmit` を通す。
- 依存追加時は `package-lock.json` を必ず更新してコミットに含める。
