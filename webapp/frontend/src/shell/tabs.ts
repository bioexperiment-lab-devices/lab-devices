/** Tab identity, order, and lab-scoping.
 *
 * This is a pure module rather than part of TabShell.tsx because vitest runs in the node
 * environment here (webapp/frontend/CLAUDE.md) — no component rendering — so anything left
 * inside the component cannot be asserted by any test in this repo. Same reason
 * builder/paletteSections.ts exists. */

export const TABS = ['Builder', 'Labs', 'Devices', 'Run', 'Records'] as const
export type Tab = (typeof TABS)[number]

/** Which tabs the selected lab actually governs.
 *
 * Typed as an exhaustive Record<Tab, boolean> rather than a set of lab-scoped names: a sixth
 * tab added later is then a compile error until it states whether it depends on a lab, which a
 * membership check would silently default to "no". Only Run binds roles to physical devices
 * (run/PreflightPanel.tsx); the Builder authors symbolic roles against the static engine
 * catalog, and Records lists every record with its own per-row lab column.
 *
 * Labs and Devices are the two entries whose `false` does NOT mean "independent of the lab".
 * Labs is the picker (LabsTab names the selected lab in its own heading and roster). Devices
 * is the manual-control tab, which carries its own inline lab switcher in its header bar. Both
 * are false because the pill would be REDUNDANT there, not because they ignore the lab. Do not
 * "fix" either to true by pattern-matching the reasons above; the test is whether the header
 * pill tells the user something the tab body does not. */
const LAB_SCOPED: Record<Tab, boolean> = {
  Builder: false,
  Labs: false,
  Devices: false,
  Run: true,
  Records: false,
}

export const labScopedTab = (tab: Tab): boolean => LAB_SCOPED[tab]
