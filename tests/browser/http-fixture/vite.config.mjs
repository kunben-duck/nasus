import { defineConfig } from '../../../apps/portal/node_modules/vite/dist/node/index.js'
import react from '../../../apps/portal/node_modules/@vitejs/plugin-react/dist/index.js'
import { fileURLToPath } from 'node:url'

// An owned browser-contract surface, with no API proxy or development runtime.
const root = fileURLToPath(new URL('../../../', import.meta.url))
export default defineConfig({
  root,
  plugins: [react()],
  resolve: { alias: {
    react: `${root}apps/portal/node_modules/react`,
    'react-dom': `${root}apps/portal/node_modules/react-dom`,
    '@tanstack/react-query': `${root}apps/portal/node_modules/@tanstack/react-query`,
  } },
  server: { host: '127.0.0.1', strictPort: true },
})
