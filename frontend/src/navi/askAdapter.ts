/**
 * 本物の AskAdapter（ask.ts の型）。POST /api/assist/ask（A1）を呼ぶ。
 * 経路・文体などの因子はサーバーが変種の旗から決めるので、画面は送る文だけを渡す。
 */
import { ask } from './api'
import type { AskAdapter } from './ask'

export function createHttpAskAdapter(): AskAdapter {
  return {
    ask(question, signal) {
      return ask({ question }, signal)
    },
  }
}
