/**
 * catch (err: unknown) で受け取ったエラーから、ログ出力用の文字列表現を取り出す共通ユーティリティ。
 * Error インスタンスならその message を、それ以外は String() で文字列化する。
 */
export function getErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}
