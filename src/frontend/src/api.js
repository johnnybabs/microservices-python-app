import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || '/api'

export async function login(email, password) {
  const res = await axios.post(`${BASE}/login`, null, {
    auth: { username: email, password }
  })
  return res.data
}

export async function uploadVideo(file, token) {
  const form = new FormData()
  form.append('file', file)
  const res = await axios.post(`${BASE}/upload`, form, {
    headers: { Authorization: `Bearer ${token}` }
  })
  return res.data
}

export async function downloadMp3(fid, token) {
  const res = await axios.get(`${BASE}/download`, {
    params: { fid },
    headers: { Authorization: `Bearer ${token}` },
    responseType: 'blob'
  })
  return res.data
}
