import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { startRelay } from './server/relay.js';

// Serwer sterowania (WebSocket, HTTP API, UDP, pad na telefon) startuje razem z `npm run dev` i `npm run preview`
const relay = {
  name: 'arcade-input-server',
  configureServer() { startRelay(); },
  configurePreviewServer() { startRelay(); },
};

export default defineConfig({
  plugins: [react(), relay],
  server: { host: true }, // gra dostępna też z innych urządzeń w sieci
  preview: { host: true },
});
