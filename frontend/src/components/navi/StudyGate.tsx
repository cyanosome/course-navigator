import PageFrame from './PageFrame'

/**
 * 調査の入口（/navi/s/<トークン>）。カードの URL から開く。学科はセッションから決まるので、学科えらびより先に出す。
 * いまは空の画面。トークンの読み取り・セッションの開始・同意・ブロックの進行は後の単位（W4）で入れる。
 */
export default function StudyGate() {
  return (
    <div className="navi-app">
      <title>調査 | コースナビ</title>
      <div className="sp">
        <header className="bar">
          <span className="brand">コースナビ</span>
        </header>
        <PageFrame>
          <h1 className="title">準備中です</h1>
        </PageFrame>
      </div>
    </div>
  )
}
