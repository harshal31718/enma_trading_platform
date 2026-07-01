import axios from 'axios'
import toast from 'react-hot-toast'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true,
})

let lastErrorToastId = null

api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Check if network error or server is down (5xx)
    if (!error.response || error.response.status >= 500) {
      const message = !error.response 
        ? 'Network error: Backend server is unreachable' 
        : `Server error: ${error.response.statusText || 'Internal Server Error'}`
      
      // Prevent toast storm by dismissing the previous one
      if (lastErrorToastId) {
        toast.dismiss(lastErrorToastId)
      }
      lastErrorToastId = toast.error(message, {
        duration: 4000,
        position: 'top-center',
      })
    }
    return Promise.reject(error)
  }
)

export default api
