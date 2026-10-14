import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Bundled with the app (SIL Open Font License), so nothing is fetched from the internet.
import '@fontsource-variable/google-sans'
import '@fontsource/google-sans-code/400.css'
import '@fontsource/google-sans-code/500.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
