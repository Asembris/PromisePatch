/// <reference types="vite/client" />

/**
 * The frontend's configuration surface, declared rather than inherited.
 *
 * Vite's own `ImportMetaEnv` carries an index signature typed `any`, which would let a typo in
 * a variable name compile and arrive as `undefined` at runtime. Naming the variables here
 * makes the set of things this app can be configured with explicit, and keeps the API base URL
 * a `string` at the one place that reads it.
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
