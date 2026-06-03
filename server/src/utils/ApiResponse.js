const ApiResponse = {
  success: (data) => ({ success: true, data }),
  created: (data) => ({ success: true, data }),
  error: (code, message) => ({ success: false, error: { code, message } }),
}

module.exports = ApiResponse
