import type { EvidenceKind } from '../../navi/types'
import Glyph from './Glyph'

interface EvidenceLabelProps {
  kind: EvidenceKind
}

const TEXT: Record<EvidenceKind, string> = {
  route: '根拠: 履修系統図',
  syllabus: '原文の引用',
  ai: '根拠: AIがシラバスから判断',
}

const CLASS: Record<EvidenceKind, string> = {
  route: 'ev ev--route',
  syllabus: 'ev ev--syl',
  ai: 'ev ev--ai',
}

export default function EvidenceLabel({ kind }: EvidenceLabelProps) {
  return (
    <span className={CLASS[kind]}>
      <Glyph name={kind} />
      {TEXT[kind]}
    </span>
  )
}
