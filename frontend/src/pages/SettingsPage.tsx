import { useEffect, useState } from 'react'
import { Save, MessageCircle } from 'lucide-react'
import { getSettings, updateSettings } from '../lib/api'

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getSettings().then(setSettings).catch(console.error)
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await updateSettings(settings)
      setSettings(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e: any) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const set = (key: string, value: string) => {
    setSettings(prev => ({ ...prev, [key]: value }))
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-white mb-6">Settings</h2>

      <div className="space-y-6 max-w-2xl">
        {/* Inference */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h3 className="text-sm font-bold text-white mb-3">Inference</h3>
          <div className="grid grid-cols-2 gap-4">
            <label className="block">
              <span className="text-xs text-gray-400">Inference FPS</span>
              <input
                type="number"
                min="1"
                max="30"
                value={settings.inference_fps || '6'}
                onChange={e => set('inference_fps', e.target.value)}
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white"
              />
            </label>
            <label className="block">
              <span className="text-xs text-gray-400">JPEG Quality (stream)</span>
              <input
                type="number"
                min="30"
                max="95"
                value={settings.jpeg_quality || '70'}
                onChange={e => set('jpeg_quality', e.target.value)}
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white"
              />
            </label>
          </div>
        </div>

        {/* WhatsApp */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <MessageCircle className="w-4 h-4 text-green-400" />
            <h3 className="text-sm font-bold text-white">WhatsApp Alerts (Green API)</h3>
          </div>
          <p className="text-xs text-gray-500 mb-4">
            Sign up at green-api.com (free), link your WhatsApp via QR code, then enter credentials below.
          </p>
          <div className="space-y-3">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={settings.whatsapp_enabled === 'true'}
                onChange={e => set('whatsapp_enabled', e.target.checked ? 'true' : 'false')}
                className="rounded border-gray-600"
              />
              <span className="text-sm text-gray-300">Enable WhatsApp notifications</span>
            </label>
            <label className="block">
              <span className="text-xs text-gray-400">Instance ID</span>
              <input
                type="text"
                value={settings.whatsapp_instance_id || ''}
                onChange={e => set('whatsapp_instance_id', e.target.value)}
                placeholder="e.g., 7103XXXXXX"
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white"
              />
            </label>
            <label className="block">
              <span className="text-xs text-gray-400">API Token</span>
              <input
                type="password"
                value={settings.whatsapp_api_token || ''}
                onChange={e => set('whatsapp_api_token', e.target.value)}
                placeholder="Your Green API token"
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white"
              />
            </label>
            <label className="block">
              <span className="text-xs text-gray-400">Recipient Phone (with country code, no +)</span>
              <input
                type="text"
                value={settings.whatsapp_recipient_phone || ''}
                onChange={e => set('whatsapp_recipient_phone', e.target.value)}
                placeholder="e.g., 918176875896"
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white"
              />
            </label>
          </div>
        </div>

        {/* Save Button */}
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 bg-cyan-500 hover:bg-cyan-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          {saving ? 'Saving...' : saved ? 'Saved!' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}
