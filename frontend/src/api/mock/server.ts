/**
 * Node-side MSW server, used by Vitest (src/test/setup.ts) so component
 * tests exercise the exact same handlers/fixtures as `npm run dev` does.
 */
import { setupServer } from 'msw/node'
import { handlers } from './handlers'

export const server = setupServer(...handlers)
