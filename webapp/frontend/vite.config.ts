/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: './', // deployable behind a prefix-stripping proxy (lab-bridge /studio route)
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': { target: 'http://localhost:8000', ws: true } },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
    env: { TZ: 'UTC' },
  },
})
