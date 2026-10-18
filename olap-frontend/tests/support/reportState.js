// Test seam for the report components.
//
// The reports are rendered on the server (there is no browser in CI and no
// DOM to click), so a markup test picks the view it exercises by replacing the
// component's useState defaults with a read from here. The data hook is
// replaced too and records what it was asked for, so a test can build its
// expectations from the very rows that were rendered.
//
// Both files are wired up by tests/report-markup.test.mjs.

let state = {}
let request = null

// The view a render starts in: { view, grain, measure, colour, sort, topN, filters }.
export const initialState = () => state
export const setInitialState = (next) => {
  state = next
}

export const recordRequest = (next) => {
  request = next
}

// The last request the component made: { report, level, params, rows }.
export const lastRequest = () => request
