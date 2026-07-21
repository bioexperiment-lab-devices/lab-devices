/** Name-aware device label: "<name> — <id>" when named, else the bare id (design §7.3).
 * Shared by the Devices tab, the Labs roster, and Run's role-mapping dropdown. */
export const deviceLabel = (d: { id: string; name: string | null }): string =>
  d.name ? `${d.name} — ${d.id}` : d.id
