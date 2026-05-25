import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Trash2, Save } from 'lucide-react'
import { getCamera, updateCamera, deleteCamera, updateModuleConfig } from '../lib/api'
import LiveFeed from '../components/LiveFeed'
import RoiDrawer from '../components/RoiDrawer'

export default function CameraPage() {
  const { id } = useParams()
  const cameraId = Number(id)
  const navigate = useNavigate()
  const [camera, setCamera] = useState<any>(null)
  const [tab, setTab] = useState<'live' | 'reception' | 'crowd'>('live')
  const [saving, setSaving] = useState(false)

  // Module config local state
  const [receptionConfig, setReceptionConfig] = useState<any>({})
  const [crowdConfig, setCrowdConfig] = useState<any>({})

  const refresh = useCallback(() => {
    getCamera(cameraId).then(c => {
      setCamera(c)
      if (c.reception_config) setReceptionConfig(c.reception_config)
      if (c.crowd_config) setCrowdConfig(c.crowd_config)
    }).catch(() => navigate('/'))
  }, [cameraId, navigate])

  useEffect(() => { refresh() }, [refresh])

  const saveConfig = async (module: string) => {
    setSaving(true)
    try {
      const data = module === 'reception' ? receptionConfig : crowdConfig
      await updateModuleConfig(cameraId, module, data)
      refresh()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('Delete this camera? This will stop the pipeline and remove all data.')) return
    await deleteCamera(cameraId)
    navigate('/')
  }

  if (!camera) return <div className="text-gray-400">Loading...</div>

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/')} className="text-gray-400 hover:text-white">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h2 className="text-xl font-bold text-white">{camera.name}</h2>
            <p className="text-gray-500 text-xs">{camera.rtsp_url}</p>
          </div>
        </div>
        <button onClick={handleDelete} className="text-red-400 hover:text-red-300 text-sm flex items-center gap-1">
          <Trash2 className="w-4 h-4" /> Delete
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 bg-gray-900 p-1 rounded-lg w-fit">
        {(['live', 'reception', 'crowd'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              tab === t ? 'bg-cyan-500/20 text-cyan-400' : 'text-gray-400 hover:text-white'
            }`}
          >
            {t === 'live' ? 'Live Feed' : t === 'reception' ? 'Reception' : 'Crowd'}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === 'live' && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <LiveFeed cameraId={cameraId} className="w-full" showMeta />
        </div>
      )}

      {tab === 'reception' && (
        <div className="space-y-4">
          {/* Config */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <h3 className="text-sm font-bold text-white mb-3">Reception Module Config</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <label className="block">
                <span className="text-xs text-gray-400">Enabled</span>
                <select
                  value={receptionConfig.enabled ? '1' : '0'}
                  onChange={e => setReceptionConfig({ ...receptionConfig, enabled: e.target.value === '1' ? 1 : 0 })}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                >
                  <option value="1">Yes</option>
                  <option value="0">No</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-gray-400">Absence Timeout (sec)</span>
                <input
                  type="number"
                  value={receptionConfig.absence_timeout_sec || 30}
                  onChange={e => setReceptionConfig({ ...receptionConfig, absence_timeout_sec: Number(e.target.value) })}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-400">Confidence</span>
                <input
                  type="number"
                  step="0.05"
                  min="0.1"
                  max="0.95"
                  value={receptionConfig.confidence_threshold || 0.4}
                  onChange={e => setReceptionConfig({ ...receptionConfig, confidence_threshold: Number(e.target.value) })}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-400">Alert Cooldown (sec)</span>
                <input
                  type="number"
                  value={receptionConfig.alert_cooldown_sec || 60}
                  onChange={e => setReceptionConfig({ ...receptionConfig, alert_cooldown_sec: Number(e.target.value) })}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                />
              </label>
            </div>
            <button
              onClick={() => saveConfig('reception')}
              disabled={saving}
              className="mt-3 flex items-center gap-1 bg-cyan-600 hover:bg-cyan-700 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
            >
              <Save className="w-3 h-3" /> {saving ? 'Saving...' : 'Save Config'}
            </button>
          </div>

          {/* ROI */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <RoiDrawer cameraId={cameraId} module="reception" onSaved={refresh} />
          </div>
        </div>
      )}

      {tab === 'crowd' && (
        <div className="space-y-4">
          {/* Config */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <h3 className="text-sm font-bold text-white mb-3">Crowd Module Config</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <label className="block">
                <span className="text-xs text-gray-400">Enabled</span>
                <select
                  value={crowdConfig.enabled ? '1' : '0'}
                  onChange={e => setCrowdConfig({ ...crowdConfig, enabled: e.target.value === '1' ? 1 : 0 })}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                >
                  <option value="1">Yes</option>
                  <option value="0">No</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-gray-400">Max People (threshold)</span>
                <input
                  type="number"
                  min="1"
                  value={crowdConfig.crowd_threshold || 5}
                  onChange={e => setCrowdConfig({ ...crowdConfig, crowd_threshold: Number(e.target.value) })}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-400">Confidence</span>
                <input
                  type="number"
                  step="0.05"
                  min="0.1"
                  max="0.95"
                  value={crowdConfig.confidence_threshold || 0.5}
                  onChange={e => setCrowdConfig({ ...crowdConfig, confidence_threshold: Number(e.target.value) })}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-400">Alert Cooldown (sec)</span>
                <input
                  type="number"
                  value={crowdConfig.alert_cooldown_sec || 60}
                  onChange={e => setCrowdConfig({ ...crowdConfig, alert_cooldown_sec: Number(e.target.value) })}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                />
              </label>
            </div>
            <button
              onClick={() => saveConfig('crowd')}
              disabled={saving}
              className="mt-3 flex items-center gap-1 bg-cyan-600 hover:bg-cyan-700 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
            >
              <Save className="w-3 h-3" /> {saving ? 'Saving...' : 'Save Config'}
            </button>
          </div>

          {/* ROI */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <RoiDrawer cameraId={cameraId} module="crowd" onSaved={refresh} />
          </div>
        </div>
      )}
    </div>
  )
}
