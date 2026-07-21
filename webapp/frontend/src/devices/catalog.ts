/** The predefined per-device-type command surface (webapp design §5).
 *
 * UI metadata ONLY — the backend forwards any `cmd` to the device generically
 * (api/deviceControl.ts, backend §6.1), so adding a command here is a source-only edit.
 * This is the analog of the Builder's block/param definitions (builder/paletteSections.ts).
 * Mirrors the typed methods in src/lab_devices/devices/*.py. */

export type ParamKind = 'number' | 'int' | 'enum' | 'bool'

export interface ParamDef {
  name: string
  label: string
  kind: ParamKind
  unit?: string
  default?: number | string | boolean
  min?: number
  max?: number
  options?: string[]
  required?: boolean
}

export interface CommandDef {
  cmd: string
  label: string
  category: 'info' | 'measure' | 'actuate' | 'cal-config'
  isJob: boolean
  params: ParamDef[]
}

export type DeviceType = 'pump' | 'valve' | 'densitometer'

const UNIVERSAL: CommandDef[] = [
  { cmd: 'ping', label: 'Ping', category: 'info', isJob: false, params: [] },
  { cmd: 'identify', label: 'Identify', category: 'info', isJob: false, params: [] },
  { cmd: 'status', label: 'Status', category: 'info', isJob: false, params: [] },
]

const DIRECTION: ParamDef = {
  name: 'direction',
  label: 'direction',
  kind: 'enum',
  options: ['forward', 'reverse'],
  default: 'forward',
  required: true,
}

const ROTATION_OPTIONS = ['shortest', 'direct', 'wrap']

export const CATALOG: Record<DeviceType, CommandDef[]> = {
  pump: [
    ...UNIVERSAL,
    { cmd: 'get_calibration', label: 'Get calibration', category: 'measure', isJob: false, params: [] },
    {
      cmd: 'dispense',
      label: 'Dispense',
      category: 'actuate',
      isJob: true,
      params: [
        { name: 'volume_ml', label: 'volume', kind: 'number', unit: 'ml', default: 1, min: 0, required: true },
        { name: 'speed_ml_min', label: 'speed', kind: 'number', unit: 'ml/min', min: 0 },
        DIRECTION,
        { name: 'drop_suckback_ml', label: 'suckback', kind: 'number', unit: 'ml', min: 0 },
      ],
    },
    {
      cmd: 'rotate',
      label: 'Rotate',
      category: 'actuate',
      isJob: false,
      params: [
        DIRECTION,
        { name: 'speed_ml_min', label: 'speed', kind: 'number', unit: 'ml/min', default: 1, min: 0, required: true },
      ],
    },
    {
      cmd: 'rotate_raw',
      label: 'Rotate (raw)',
      category: 'actuate',
      isJob: false,
      params: [
        DIRECTION,
        { name: 'speed_pct', label: 'speed', kind: 'number', unit: '%', default: 10, min: 0, max: 100, required: true },
      ],
    },
    { cmd: 'pause', label: 'Pause', category: 'actuate', isJob: false, params: [] },
    { cmd: 'resume', label: 'Resume', category: 'actuate', isJob: false, params: [] },
    {
      cmd: 'start_calibration',
      label: 'Start calibration',
      category: 'cal-config',
      isJob: true,
      params: [{ name: 'speed_pct', label: 'speed', kind: 'number', unit: '%', min: 0, max: 100 }],
    },
    {
      cmd: 'set_calibration',
      label: 'Set calibration',
      category: 'cal-config',
      isJob: false,
      params: [
        { name: 'measured_volume_ml', label: 'measured volume', kind: 'number', unit: 'ml', min: 0 },
        { name: 'ml_per_step', label: 'ml/step', kind: 'number', unit: 'ml' },
      ],
    },
  ],
  valve: [
    ...UNIVERSAL,
    {
      cmd: 'home',
      label: 'Home',
      category: 'actuate',
      isJob: false,
      params: [{ name: 'position', label: 'position', kind: 'int', default: 1, min: 1, required: true }],
    },
    {
      cmd: 'set_position',
      label: 'Set position',
      category: 'actuate',
      isJob: true,
      params: [
        { name: 'position', label: 'position', kind: 'int', default: 1, min: 1, required: true },
        { name: 'rotation', label: 'rotation', kind: 'enum', options: ROTATION_OPTIONS },
      ],
    },
    {
      cmd: 'configure',
      label: 'Configure',
      category: 'cal-config',
      isJob: false,
      params: [
        { name: 'default_rotation', label: 'default rotation', kind: 'enum', options: ROTATION_OPTIONS },
        { name: 'hold_torque', label: 'hold torque', kind: 'bool' },
      ],
    },
  ],
  densitometer: [
    ...UNIVERSAL,
    {
      cmd: 'measure',
      label: 'Measure',
      category: 'measure',
      isJob: true,
      params: [{ name: 'include_raw', label: 'include raw', kind: 'bool' }],
    },
    { cmd: 'measure_blank', label: 'Measure blank', category: 'measure', isJob: true, params: [] },
    {
      cmd: 'get_readings',
      label: 'Get readings',
      category: 'measure',
      isJob: false,
      params: [
        { name: 'since_seq', label: 'since seq', kind: 'int', min: 0 },
        { name: 'limit', label: 'limit', kind: 'int', min: 1 },
      ],
    },
    {
      cmd: 'read_raw',
      label: 'Read raw',
      category: 'measure',
      isJob: true,
      params: [{ name: 'level', label: 'LED level', kind: 'int', min: 0, max: 255 }],
    },
    {
      cmd: 'start_monitoring',
      label: 'Start monitoring',
      category: 'actuate',
      isJob: false,
      params: [{ name: 'interval_s', label: 'interval', kind: 'number', unit: 's', min: 0 }],
    },
    { cmd: 'stop_monitoring', label: 'Stop monitoring', category: 'actuate', isJob: false, params: [] },
    {
      cmd: 'set_led',
      label: 'Set LED',
      category: 'actuate',
      isJob: false,
      params: [{ name: 'level', label: 'level', kind: 'int', default: 128, min: 0, max: 255, required: true }],
    },
    {
      cmd: 'set_thermostat',
      label: 'Set thermostat',
      category: 'cal-config',
      isJob: false,
      params: [
        { name: 'enabled', label: 'enabled', kind: 'bool', default: true, required: true },
        { name: 'target_c', label: 'target', kind: 'number', unit: '°C' },
      ],
    },
    {
      cmd: 'set_tube_correction',
      label: 'Set tube correction',
      category: 'cal-config',
      isJob: false,
      params: [{ name: 'factor', label: 'factor', kind: 'number', default: 1, required: true }],
    },
    {
      cmd: 'calibrate_tube',
      label: 'Calibrate tube',
      category: 'cal-config',
      isJob: false,
      params: [{ name: 'reference_absorbance', label: 'reference absorbance', kind: 'number', default: 0, required: true }],
    },
  ],
}

/** Bounded, visibly-actuating command per type — the aid for identifying which physical
 * unit is which before naming it (design §4). Runs through the same execution path. */
export const LOCATE: Record<DeviceType, { cmd: string; params: Record<string, unknown> }> = {
  pump: { cmd: 'dispense', params: { volume_ml: 0.2, direction: 'forward' } },
  valve: { cmd: 'set_position', params: { position: 1 } },
  densitometer: { cmd: 'measure', params: {} },
}

export const commandsFor = (type: string): CommandDef[] =>
  (CATALOG as Record<string, CommandDef[]>)[type] ?? []
