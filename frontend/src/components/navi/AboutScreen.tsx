import { useNavi } from '../../navi/state'
import PageFrame from './PageFrame'

/** このAIについて（W8。メニューから）。見出しは1つと短い見出し語だけ、本文は 16px と 14px（E1 の方針） */
export default function AboutScreen() {
  const { dept } = useNavi()
  return (
    <PageFrame>
      <h1 className="title">このAIについて</h1>
      <section className="sec">
        <h2 className="sec-label">何をするか</h2>
        <p className="lead">
          公開シラバスと履修系統図から、科目のつながりを調べ、科目とその順番を提案します。時間割に入れて、曜限の重なりと単位を確かめられます。
        </p>
      </section>
      <section className="sec">
        <h2 className="sec-label">使っている情報</h2>
        <p className="text">
          {dept.university} {dept.syllabusYear}年度シラバス、{dept.name}の履修系統図（PDF の線を自動で読み取ったもの）
        </p>
        <p className="src">
          この画面はモックです。科目・担当・区分・曜限・単位・授業計画・卒業に要る単位は架空の見本で、本物のシラバスではありません。
        </p>
      </section>
      <section className="sec">
        <h2 className="sec-label">どこにAIを使っているか</h2>
        <p className="text">
          おすすめ、興味関心ごとの一覧、取る順、時間割の重なりと単位は、系統図とシラバスから決まった規則で作っています（AIは使っていません）。上の探す欄に書いた文への回答と理由はAIが作ります。間違うことがあるので、シラバスの原文で確かめてください。そこで入力した文は外部のAIサービスに送られます。
        </p>
      </section>
      <section className="sec">
        <h2 className="sec-label">できないこと</h2>
        <p className="text">難しさ、単位の取りやすさ、評判の比較。履修登録。</p>
      </section>
      <section className="sec">
        <h2 className="sec-label">最終確認</h2>
        <p className="text">履修の手引きと大学のシステムで行ってください。</p>
      </section>
    </PageFrame>
  )
}
