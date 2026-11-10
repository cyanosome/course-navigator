/**
 * 調査モードの設定（UX 仕様 S4 の「フロントの設定ファイル」に当たる）。画面モック用の仮の値。
 * アンケートの URL は仮。example.com は説明用に予約されたドメインで、実在のアンケートではない。
 * 学科の見本のデータ（fixtureDepartment.ts）を本番の束に入れないため、別のファイルに分けた。
 */
export const FIXTURE_STUDY_CONFIG = {
  appVersion: 'v0.4-mock',
  surveyUrl: 'https://example.com/survey',
  /** 事前入力の欄の名前（仮）。数だけを入れる（UX 仕様 C22） */
  prefillKeys: {
    session: 'session',
    kept: 'kept',
    keptAfterReason: 'kept_after_reason',
    detailOpened: 'detail_opened',
    originalOpened: 'original_opened',
    traversed: 'traversed',
    asked: 'asked',
  },
} as const
