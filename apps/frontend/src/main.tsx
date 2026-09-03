import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { App } from './app/App'
import { createQueryClient } from './app/queryClient'
import './index.css'

const container = document.getElementById('root')
if (container === null) throw new Error('the #root element is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={createQueryClient()}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
