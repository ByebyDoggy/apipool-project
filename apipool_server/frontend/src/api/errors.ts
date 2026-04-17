/**
 * Extract a human-readable error message from Axios error responses.
 * Handles FastAPI 422 validation errors (detail is an array) and regular error objects.
 */
export function extractErrorMessage(err: any, fallback = '操作失败'): string {
  if (!err?.response?.data) return fallback

  const data = err.response.data

  // FastAPI 422 validation error: detail is an array of objects
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((e: any) => {
        const field = e.loc?.slice(1).join('.') || ''
        return field ? `${field}: ${e.msg}` : e.msg
      })
      .join('; ')
  }

  // Regular error: detail is a string
  if (typeof data.detail === 'string') {
    return data.detail
  }

  // Fallback to message field
  if (typeof data.message === 'string') {
    return data.message
  }

  return fallback
}
