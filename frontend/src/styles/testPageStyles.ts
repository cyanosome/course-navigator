import type { CSSProperties } from 'react'

/**
 * PostgresTest / Neo4jTest / IntegratedTest の3画面でほぼ同一だったインラインスタイル定義。
 * 各コンポーネントはこのオブジェクトをベースに、必要な箇所だけスプレッドで上書き・追加して使う。
 *
 * NOTE: IntegratedTest はフォーム密度が高く、余白やフォントサイズを一回り小さくしているため、
 * 該当キー（form / formGroup / label / input / textarea / button / alert / list / listItem /
 * itemHeader / itemId / itemTitle / itemDescription）はコンポーネント側で上書きしている。
 */
export const testPageStyles: Record<string, CSSProperties> = {
  container: {
    padding: '2rem',
    maxWidth: '1200px',
    margin: '0 auto',
    textAlign: 'left',
    boxSizing: 'border-box',
    width: '100%',
  },
  title: {
    fontSize: '2.5rem',
    marginBottom: '0.5rem',
    color: 'var(--text-h)',
    fontWeight: 500,
  },
  subtitle: {
    fontSize: '1rem',
    color: 'var(--text)',
    marginBottom: '2rem',
  },
  alert: {
    padding: '1rem',
    borderRadius: '8px',
    border: '1px solid',
    marginBottom: '1.5rem',
    fontSize: '0.95rem',
    transition: 'all 0.3s ease',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
    gap: '2rem',
    alignItems: 'start',
  },
  card: {
    background: 'var(--social-bg)',
    border: '1px solid var(--border)',
    borderRadius: '12px',
    padding: '2rem',
    boxShadow: 'var(--shadow)',
  },
  cardTitle: {
    fontSize: '1.5rem',
    marginBottom: '1.5rem',
    color: 'var(--text-h)',
    borderBottom: '2px solid var(--border)',
    paddingBottom: '0.5rem',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '1.2rem',
  },
  formGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  label: {
    fontSize: '0.9rem',
    fontWeight: 'bold',
    color: 'var(--text-h)',
  },
  input: {
    padding: '0.75rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--bg)',
    color: 'var(--text-h)',
    fontSize: '1rem',
    outline: 'none',
  },
  textarea: {
    padding: '0.75rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--bg)',
    color: 'var(--text-h)',
    fontSize: '1rem',
    minHeight: '100px',
    outline: 'none',
    resize: 'vertical',
  },
  button: {
    padding: '0.75rem 1.5rem',
    borderRadius: '6px',
    border: 'none',
    background: 'var(--accent)',
    color: '#fff',
    fontSize: '1rem',
    fontWeight: 'bold',
    cursor: 'pointer',
    transition: 'opacity 0.2s',
  },
  searchForm: {
    display: 'flex',
    gap: '0.5rem',
    marginBottom: '1.5rem',
  },
  searchInput: {
    flex: 1,
    padding: '0.75rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--bg)',
    color: 'var(--text-h)',
    fontSize: '1rem',
    outline: 'none',
  },
  searchButton: {
    padding: '0.75rem 1.2rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--code-bg)',
    color: 'var(--text-h)',
    cursor: 'pointer',
  },
  loading: {
    textAlign: 'center',
    padding: '2rem 0',
    color: 'var(--text)',
  },
  noData: {
    textAlign: 'center',
    padding: '2rem 0',
    color: 'var(--text)',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: '1rem',
    maxHeight: '400px',
    overflowY: 'auto',
    paddingRight: '0.5rem',
  },
  listItem: {
    padding: '1rem',
    borderRadius: '8px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  itemHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
  },
  itemTitle: {
    fontSize: '1.1rem',
    fontWeight: 500,
    color: 'var(--text-h)',
  },
  itemId: {
    fontSize: '0.8rem',
    color: 'var(--text)',
    fontFamily: 'var(--mono)',
  },
  itemDescription: {
    fontSize: '0.9rem',
    color: 'var(--text)',
    margin: 0,
  },
}

/** message.type に応じた alert の配色。3画面で共通のロジック。 */
export function getAlertStyle(
  base: CSSProperties,
  type: 'success' | 'error',
): CSSProperties {
  return {
    ...base,
    backgroundColor: type === 'success' ? 'var(--accent-bg)' : 'rgba(239, 68, 68, 0.1)',
    borderColor: type === 'success' ? 'var(--accent-border)' : 'rgba(239, 68, 68, 0.4)',
    color: type === 'success' ? 'var(--accent)' : '#ef4444',
  }
}
