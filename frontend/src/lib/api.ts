const BASE = '/api'

async function request(path: string, options?: RequestInit) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

// Cameras
export const getCameras = () => request('/cameras')
export const getCamera = (id: number) => request(`/cameras/${id}`)
export const addCamera = (name: string, rtsp_url: string) =>
  request('/cameras', { method: 'POST', body: JSON.stringify({ name, rtsp_url }) })
export const updateCamera = (id: number, data: any) =>
  request(`/cameras/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteCamera = (id: number) =>
  request(`/cameras/${id}`, { method: 'DELETE' })
export const getSnapshotUrl = (id: number) => `${BASE}/cameras/${id}/snapshot`

// ROI
export const getRoi = (cameraId: number, module: string) =>
  request(`/cameras/${cameraId}/roi/${module}`)
export const saveRoi = (cameraId: number, module: string, polygon: number[][]) =>
  request(`/cameras/${cameraId}/roi/${module}`, {
    method: 'PUT', body: JSON.stringify({ polygon }),
  })

// Module Config
export const getModuleConfig = (cameraId: number, module: string) =>
  request(`/cameras/${cameraId}/config/${module}`)
export const updateModuleConfig = (cameraId: number, module: string, data: any) =>
  request(`/cameras/${cameraId}/config/${module}`, {
    method: 'PUT', body: JSON.stringify(data),
  })

// Alerts
export const getAlerts = (params?: Record<string, string>) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return request(`/alerts${qs}`)
}
export const getActiveAlertCount = () => request('/alerts/active-count')
export const acknowledgeAlert = (id: number) =>
  request(`/alerts/${id}/acknowledge`, { method: 'POST' })
export const resolveAlert = (id: number) =>
  request(`/alerts/${id}/resolve`, { method: 'POST' })
export const getAlertSnapshotUrl = (filename: string) =>
  `${BASE}/alerts/snapshot/${filename}`

// Settings
export const getSettings = () => request('/settings')
export const updateSettings = (settings: Record<string, string>) =>
  request('/settings', { method: 'PUT', body: JSON.stringify({ settings }) })
