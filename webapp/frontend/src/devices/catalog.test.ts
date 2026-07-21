import { describe, expect, it } from 'vitest'
import { CATALOG, LOCATE, commandsFor, type CommandDef } from './catalog'

const all: CommandDef[] = Object.values(CATALOG).flat()

describe('catalog integrity', () => {
  it('every device type has the universal info commands', () => {
    for (const cmds of Object.values(CATALOG)) {
      const names = cmds.map((c) => c.cmd)
      expect(names).toEqual(expect.arrayContaining(['ping', 'identify', 'status']))
    }
  })

  it('every param has a valid kind and enum params list options', () => {
    for (const cmd of all) {
      for (const p of cmd.params) {
        expect(['number', 'int', 'enum', 'bool']).toContain(p.kind)
        if (p.kind === 'enum') expect(p.options && p.options.length > 0).toBe(true)
      }
    }
  })

  it('every command has a non-empty label and known category', () => {
    for (const cmd of all) {
      expect(cmd.label.length).toBeGreaterThan(0)
      expect(['info', 'measure', 'actuate', 'cal-config']).toContain(cmd.category)
    }
  })

  it('no duplicate command names within a device type', () => {
    for (const cmds of Object.values(CATALOG)) {
      const names = cmds.map((c) => c.cmd)
      expect(new Set(names).size).toBe(names.length)
    }
  })

  it('locate presets reference a real command of that type', () => {
    for (const [type, locate] of Object.entries(LOCATE)) {
      const cmds = CATALOG[type as keyof typeof CATALOG].map((c) => c.cmd)
      expect(cmds).toContain(locate.cmd)
    }
  })

  it('commandsFor returns the type list, [] for an unknown type', () => {
    expect(commandsFor('pump')).toBe(CATALOG.pump)
    expect(commandsFor('spectrometer')).toEqual([])
  })
})
