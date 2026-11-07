/**
 * 本物の AskAdapter（ask.ts の型）。POST /api/assist/ask（A1）を呼ぶ。
 * 経路・文体などの因子はサーバーが変種の旗から決めるので、画面は送る文と記録用の値（打った文・chat_send の event_id）だけを渡す。
 */
import { ask } from './api'
import type { AskAdapter } from './ask'

export function createHttpAskAdapter(): AskAdapter {
  return {
    ask({ question, rawInput, clientEventId, planContext }, signal) {
      return ask(
        {
          question,
          raw_input: rawInput,
          ...(clientEventId === null ? {} : { client_event_id: clientEventId }),
          ...(planContext === undefined ? {} : { plan_context: planContext }),
        },
        signal,
      )
    },
  }
}
