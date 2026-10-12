// Runs before the tests. Adds helpers such as expect(...).toBeInTheDocument().
import '@testing-library/jest-dom/vitest'

// The pretend browser used in tests has no ResizeObserver, which the chart
// library asks for. An empty stand-in is enough.
globalThis.ResizeObserver =
  globalThis.ResizeObserver ||
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
