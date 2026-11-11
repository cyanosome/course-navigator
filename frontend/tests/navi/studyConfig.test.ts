/**
 * studyConfig.ts の、リンクで配る調査の設定。同意の記録に送る固定の番号が backend の形に合うことと、最後の質問票の数
 * （backend の check が study の final_questionnaires で見る数。CLI の既定は 2）。
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FORM_SERIAL_PATTERN } from '../../src/navi/apiTypes.ts'
import { ONLINE_FORM_SERIAL, QUESTIONNAIRE_SETS } from '../../src/navi/studyConfig.ts'

test('同意の記録に送る固定の番号は、backend の form_serial の形に合う', () => {
  assert.match(ONLINE_FORM_SERIAL, FORM_SERIAL_PATTERN)
})

test('ibuki_sus の最後の質問票は二択と振り返りの2件で、振り返りはすべて任意の自由記述', () => {
  const final = QUESTIONNAIRE_SETS.ibuki_sus.final
  assert.deepEqual(
    final.map((q) => q.scale),
    ['二択', '振り返り'],
  )
  const reflection = final[1]
  assert.ok(reflection !== undefined)
  assert.deepEqual(
    reflection.items.map((it) => [it.id, it.kind, it.required]),
    [1, 2, 3, 4, 5, 6].map((n) => [`r${n}`, 'text', false]),
  )
})
