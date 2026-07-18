/** StreamsPanel filter (audit F10): a 30+ stream doc needs a way to narrow the flat
 * list. Same semantics as LoadDialog's search — case-insensitive substring. */
export function filterStreamNames(names: string[], query: string): string[] {
  const q = query.trim().toLowerCase()
  if (q === '') return names
  return names.filter((n) => n.toLowerCase().includes(q))
}
