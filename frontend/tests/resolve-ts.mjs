/**
 * 単体テスト（npm test）を Node の test runner で、src の .ts をそのまま読んで回すための読み込みの口。
 * src は Vite の書き方（相対の import に拡張子を書かない）なので、見つからなければ .ts を足して探す。
 * 型は Node が外すだけで検査しない（型の検査は npm run build の tsc -b）。
 */
import { registerHooks } from 'node:module'

const RELATIVE = /^\.\.?\//
const HAS_EXTENSION = /\.[cm]?[jt]sx?$/

registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context)
    } catch (err) {
      if (err?.code !== 'ERR_MODULE_NOT_FOUND' || !RELATIVE.test(specifier) || HAS_EXTENSION.test(specifier)) throw err
      return nextResolve(`${specifier}.ts`, context)
    }
  },
})
