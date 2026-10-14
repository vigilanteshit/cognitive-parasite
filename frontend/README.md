# The Data Parasite workbench

React, TypeScript, and Vite frontend for the local cognitive memory research API.

```sh
npm ci
npm run dev
```

Start the FastAPI server on `127.0.0.1:8000`. Vite forwards `/api` requests to that server. The production build uses same-origin `/api` requests and is served by the backend from `frontend/dist`.

```sh
npm run build
npm test
npm run test:browser
```

Browser tests use installed Google Chrome and deterministic API fixtures. They verify source ingestion, streamed responses, checkpoint resume, session memory, console errors, and layout at 320, 768, 1024, and 1440 pixels. If Chrome is unavailable, install Playwright Chromium and replace `channel: 'chrome'` with the default browser in `playwright.config.ts`.

The frontend receives model availability and demo mode from the server. Credentials remain on the server. It renders no invented conversations, sources, memory, execution steps, or token counters. The inspector shows the current run's reported evidence and execution. Memory persists per session. Stopped or budget-limited runs can resume from the server's saved checkpoint; EventSource closes on terminal events and resumes with the returned event cursor.

Keyboard: Enter sends, Shift + Enter inserts a new line. Arrow keys move between inspector tabs. Source dialogs use the browser's native focus management. Animations honor reduced motion.
