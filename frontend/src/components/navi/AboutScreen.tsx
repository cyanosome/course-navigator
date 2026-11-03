import { useNavi } from '../../navi/state'
import BackButton from './BackButton'

/** このAIについて（W8）。文言は UX 仕様 6.2 W8 のまま。取得日は仮 */
export default function AboutScreen() {
  const { dept, isPc } = useNavi()
  return (
    <main className={isPc ? 'p-page page' : 'm-main page'}>
      <BackButton />
      <h1>このAIについて</h1>
      <section>
        <h2>何をするか</h2>
        <p className="body-s">
          公開シラバスと履修系統図から、科目のつながり（どの枠からどの枠へ線があるか）を調べ、科目とその順番を提案します。
        </p>
      </section>
      <section>
        <h2>使っている情報</h2>
        <ul className="body-s bullets">
          <li>
            {dept.university} {dept.syllabusYear}年度シラバス（取得日 ○/○）
          </li>
          <li>{dept.name} 履修系統図（PDF の線を自動で読み取ったもの）</li>
        </ul>
        <p className="note">この画面はモックです。科目・枠・授業計画は架空の見本で、本物のシラバスではありません。</p>
      </section>
      <section>
        <h2>どこにAIを使っているか</h2>
        <p className="body-s">
          方向・取る順・前後の枠は、系統図から機械的に作っています（AIは使っていません）。「自分の言葉で探す」の回答と理由はAIが作ります。間違うことがあるので、シラバス原文で確かめてください。そこで入力した文は外部のAIサービスに送られます。
        </p>
      </section>
      <section>
        <h2>できないこと</h2>
        <p className="body-s">難しさ・単位の取りやすさ・評判、時間割の重なりの確認、履修登録</p>
      </section>
      <section>
        <h2>最終確認</h2>
        <p className="body-s">履修の手引きと大学のシステムで行ってください。</p>
      </section>
    </main>
  )
}
