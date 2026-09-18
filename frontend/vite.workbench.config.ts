import { resolve } from 'node:path'
import vue from '@vitejs/plugin-vue'
import UnoCSS from 'unocss/vite'
import { defineConfig, type Plugin } from 'vite'

function workbenchRootRedirect(): Plugin {
  return {
    name: 'workbench-root-redirect',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (req.url === '/' || req.url === '/index.html') {
          req.url = '/workbench.html'
        }
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [vue(), UnoCSS(), workbenchRootRedirect()],
  define: {
    'import.meta.env.VITE_WORKBENCH': JSON.stringify('true'),
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5180,
    open: '/workbench.html',
    // Public demo tunnels (cloudflared / cpolar) send a non-local Host header.
    allowedHosts: ['.trycloudflare.com', '.cpolar.cn', '.cpolar.io'],
    proxy: {
      '/api': 'http://127.0.0.1:8877',
    },
  },
  build: {
    rollupOptions: {
      input: resolve(__dirname, 'workbench.html'),
    },
  },
})
