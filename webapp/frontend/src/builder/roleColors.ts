/** Per-role swatch colours (design 2026-07-18-canvas-visual-language §3.3).
 *
 * User-settled 2026-07-18: colours are auto-assigned from a fixed ramp in role-declaration
 * order, every command and measure of a role shares its colour, the assignment persists
 * keyed by role type + name, and the user may edit a colour or remove it entirely (a role
 * with no colour renders exactly as cards did before this increment — plain white).
 *
 * Swatches sit at full -500/-600 saturation against the construct tints' pale -50/-200
 * (constructTint.ts). That saturation gap is what keeps the two systems legible as separate
 * languages rather than one muddle, and a small solid swatch reads conventionally as a
 * LEGEND KEY rather than a status — which is what keeps it from competing with the
 * border-and-background state palette.
 */

/** Written out in full: Tailwind 4 scans source text, so `bg-${family}-500` yields no CSS.
 *
 * Same reserved-hue exclusion as the construct tints — no blue/indigo/sky (selection), no
 * red/rose (error), no amber/orange/yellow (warning), no emerald/green (valid). `lime` and
 * `cyan` take the -600 step because their -500 steps are too light to read as a solid key
 * at swatch size. */
export const ROLE_SWATCH_CLASSES = [
  'bg-teal-500',
  'bg-violet-500',
  'bg-fuchsia-500',
  'bg-lime-600',
  'bg-cyan-600',
  'bg-purple-500',
  'bg-pink-500',
  'bg-stone-500',
] as const

export type RoleSwatchClass = (typeof ROLE_SWATCH_CLASSES)[number]

/** Human-readable name for each ramp swatch. Colocated with `ROLE_SWATCH_CLASSES` so the
 * two never drift apart — the picker's swatch buttons use this for `title`/`aria-label`
 * instead of the raw Tailwind class string (a screen reader announcing "bg-teal-500 button"
 * is an implementation detail leaking into the accessibility layer). Keyed by class rather
 * than by ramp index so a future reorder of `ROLE_SWATCH_CLASSES` can't silently pair a
 * swatch with the wrong name. */
export const ROLE_SWATCH_LABELS: Record<RoleSwatchClass, string> = {
  'bg-teal-500': 'Teal',
  'bg-violet-500': 'Violet',
  'bg-fuchsia-500': 'Fuchsia',
  'bg-lime-600': 'Lime',
  'bg-cyan-600': 'Cyan',
  'bg-purple-500': 'Purple',
  'bg-pink-500': 'Pink',
  'bg-stone-500': 'Stone',
}

/** Persistence key. Type is part of it so `pump:x` and `sensor:x` are different roles —
 * a bare name would let a rename-and-retype silently inherit the old colour. */
export function roleColorKey(name: string, type: string): string {
  return `${type}:${name}`
}

/** Resolve every declared role to a swatch class, or to null for "no colour".
 *
 * Auto-assignment is POSITIONAL — index into the ramp by declaration order — so clearing
 * one role's colour must not renumber its neighbours. That is why an override is applied
 * over the positional result rather than removing the role from the numbering.
 *
 * `overrides` distinguishes three states: a class means the user picked it, an explicit
 * `null` means the user removed the colour, and an absent key means untouched (auto).
 */
export function assignRoleColors(
  roles: Record<string, { type: string }>,
  overrides: Record<string, string | null>,
): Record<string, string | null> {
  const out: Record<string, string | null> = {}
  Object.entries(roles).forEach(([name, { type }], i) => {
    const key = roleColorKey(name, type)
    out[name] = key in overrides
      ? overrides[key]
      : ROLE_SWATCH_CLASSES[i % ROLE_SWATCH_CLASSES.length]
  })
  return out
}
