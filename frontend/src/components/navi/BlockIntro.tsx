import { blockLabel, isPracticeBlock } from '../../navi/studyConfig'

interface BlockIntroProps {
  block: number
  /** この調査の最初のブロックか（説明の文を出す） */
  first: boolean
  /** 前のブロックと画面が変わるか（練習の後の最初の画面では変わらない） */
  changed: boolean
  busy: boolean
  onStart: () => void
}

/**
 * ブロックの前の画面。参加者には条件を伏せ、「練習」「画面1」「画面2」とだけ呼ぶ（計画 4.1）。
 * ［始める］で R4（ブロックの開始）を呼び、そのブロックの旗と課題を受け取る。
 */
export default function BlockIntro({ block, first, changed, busy, onStart }: BlockIntroProps) {
  return (
    <>
      <h1 className="title">{blockLabel(block)}</h1>
      <section className="sec">
        {isPracticeBlock(block) ? (
          <p className="lead">まず練習です。画面に慣れるための短い課題を解きます。</p>
        ) : (
          <p className="lead">{changed ? 'ここから画面が変わります。この画面で課題を解きます。' : 'この画面で課題を解きます。'}</p>
        )}
        {first && (
          <>
            <p className="text">使いにくいところを見つけるのが目的です。うまく使えなくても、あなたのせいではありません。</p>
            <p className="text">名前や学籍番号は入力しないでください。</p>
          </>
        )}
      </section>
      <div className="page-acts">
        <button className="primary" type="button" disabled={busy} onClick={onStart}>
          始める
        </button>
      </div>
    </>
  )
}
