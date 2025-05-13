import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['vite.svg', 'icons/*.{png,PNG}'],
      manifest: {
        name: 'Arbitrage Bot',
        short_name: 'Arbitrage Bot',
        theme_color: '#000000',
        background_color: '#000000',
        display: 'standalone',
        orientation: 'portrait',
        scope: '/arbitrage-bot-frontend/',
        start_url: '/arbitrage-bot-frontend/',
        icons: [
          {
            src: '/arbitrage-bot-frontend/icons/arbitrage-bot-icon-192.png',
            sizes: '192x192',
            type: 'image/png'
          },
          {
            src: '/arbitrage-bot-frontend/icons/arbitrage-bot-icon-512.png',
            sizes: '512x512',
            type: 'image/png'
          }
        ]
      }
    })
  ],
  base: '/arbitrage-bot-frontend/',
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})

