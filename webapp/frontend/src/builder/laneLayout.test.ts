import { describe, expect, it } from 'vitest'
import { CONTROL_H_PX } from '../ui/controls'
import {
  LANE_DIVIDER_INSET,
  LANE_DIVIDER_TOP_PX,
  LANE_EDGE_W,
  LANE_GUTTER_W,
  LANE_PAD,
  LANE_PAD_PX,
} from './laneLayout'

/** Tailwind's spacing unit is 4px, so `mt-7` is 28px. The tokens are literals because the class
 * scanner cannot see a template string, which is why this test checks the arithmetic behind them
 * rather than generating them from it. */
const px = (cls: string): number => Number(cls.match(/-(\d+)$/)![1]) * 4

describe('lane layout tokens', () => {
  it('makes an inter-lane gutter exactly two edge insets wide', () => {
    // 8px of air on each side of every lane: where two lanes meet, their two margins add up to
    // the gutter and the hairline sits in the middle of it. Anything else and the separator is
    // closer to one lane than the other, which is what comment #5 reported.
    expect(px(LANE_EDGE_W)).toBe(8)
    expect(px(LANE_GUTTER_W)).toBe(2 * px(LANE_EDGE_W))
  })

  it('gives a lane vertical padding only', () => {
    // Horizontal padding here would stack on top of the gutter and push this lane's cards deeper
    // than a loop's body — the defect itself.
    expect(LANE_PAD).toBe('py-1')
    expect(px(LANE_PAD)).toBe(LANE_PAD_PX)
  })

  it('starts the divider below the lane label row', () => {
    // The label row is one CONTROL_H tall and sits inside the lane's padding, so the hairline
    // clears it by exactly that sum. If the control token ever moves, this fails and the inset
    // must move with it — otherwise the line runs back into the tinted header (comment #5).
    expect(LANE_DIVIDER_TOP_PX).toBe(LANE_PAD_PX + CONTROL_H_PX)
    const [top, bottom] = LANE_DIVIDER_INSET.split(' ')
    expect(px(top)).toBe(LANE_DIVIDER_TOP_PX)
    expect(px(bottom)).toBe(LANE_PAD_PX)
  })
})
