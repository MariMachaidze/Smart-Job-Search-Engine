import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from '../api/mock/server'
import { resetMockStore } from '../api/mock/data'

// Every component test runs against the same MSW handlers the dev server
// uses -- see src/api/mock/handlers.ts. This keeps "it compiles" tests
// from being the only kind written: tests here hit real fetch() calls
// that are intercepted and answered with realistic fixture data.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetMockStore()
  localStorage.clear()
})
afterAll(() => server.close())
