import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DemandCalendarReport from '../../src/reports/DemandCalendarReport.jsx'

export { setInitialState, lastRequest } from './reportState.js'
export { sortRows } from '../../src/components/DataTable.jsx'

export const render = () => renderToStaticMarkup(createElement(DemandCalendarReport))
