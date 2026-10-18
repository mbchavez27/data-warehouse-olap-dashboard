import { Component } from 'react'
import ErrorPage from './ErrorPage.jsx'

// Catches a crash while rendering a page, so a bug in one report shows a
// "something went wrong" page instead of blanking the whole app; the sidebar
// keeps working. App keys it by the open page, so moving to another page
// clears the error.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Page crashed:', error, info?.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <ErrorPage
        code="Something went wrong"
        title="This page hit an error"
        details={String(error?.stack || error)}
        actions={
          <>
            <button type="button" className="button button-primary" onClick={() => window.location.reload()}>
              Reload the page
            </button>
            <a href="#home" className="button">
              Go to the home page
            </a>
          </>
        }
      >
        <p>
          The dashboard ran into a problem showing this page. Reloading usually fixes it. If it keeps happening, try
          another report from the sidebar.
        </p>
      </ErrorPage>
    )
  }
}
