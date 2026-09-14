import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { App } from './app/App'
import { createQueryClient } from './app/queryClient'
import { publishTurnTimings } from './instrumentation/turnTiming'
import './index.css'

const container = document.getElementById('root')
if (container === null) throw new Error('the #root element is missing from index.html')

// So the instants a real browser session recorded can be read back out of it afterwards. It
// exposes readers only, computes nothing, and no measurement has been taken from it.
publishTurnTimings()

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={createQueryClient()}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
