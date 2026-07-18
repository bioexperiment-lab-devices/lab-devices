/** The palette's block-chip sections (design 2026-07-18 §3).
 *
 * Plain data in its own module so `paletteSections.test.ts` can assert the partition: vitest
 * runs in a node env with no rendering (webapp/frontend/CLAUDE.md), so a test cannot import
 * Palette.tsx — React, dnd-kit, and the zustand stores come with it.
 *
 * Chip order within Flow is a deliberate progression: composition, then decision, then
 * repetition. */
import type { DataKind, FlowKind, PauseKind, SafetyKind, PaletteKind } from './tree'

export interface BlockChip {
  kind: PaletteKind
  title: string
}

export const FLOW: Array<{ kind: FlowKind; title: string }> = [
  { kind: 'serial', title: 'Serial' },
  { kind: 'parallel', title: 'Parallel' },
  { kind: 'branch', title: 'Branch' },
  { kind: 'loop', title: 'Loop' },
  { kind: 'for_each', title: 'For each' },
]

export const DATA: Array<{ kind: DataKind; title: string }> = [
  { kind: 'compute', title: 'Compute' },
  { kind: 'record', title: 'Record' },
]

export const PAUSE: Array<{ kind: PauseKind; title: string }> = [
  { kind: 'wait', title: 'Wait' },
  { kind: 'operator_input', title: 'Operator input' },
]

export const SAFETY: Array<{ kind: SafetyKind; title: string }> = [
  { kind: 'alarm', title: 'Alarm' },
  { kind: 'abort', title: 'Abort' },
]

export const BLOCK_SECTIONS: Array<{ title: string; items: readonly BlockChip[] }> = [
  { title: 'Flow', items: FLOW },
  { title: 'Data', items: DATA },
  { title: 'Pause', items: PAUSE },
  { title: 'Safety', items: SAFETY },
]
