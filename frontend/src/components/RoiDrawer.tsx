import { useEffect, useRef, useState } from 'react'
import { getSnapshotUrl, saveRoi, getRoi } from '../lib/api'
import { Pencil, Trash2, Check } from 'lucide-react'

interface Props {
  cameraId: number
  module: 'reception' | 'crowd'
  onSaved?: () => void
}

export default function RoiDrawer({ cameraId, module, onSaved }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imgRef = useRef<HTMLImageElement | null>(null)
  const [points, setPoints] = useState<number[][]>([])
  const [savedPoints, setSavedPoints] = useState<number[][] | null>(null)
  const [drawing, setDrawing] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)

  // Load snapshot and existing ROI
  useEffect(() => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      imgRef.current = img
      setLoaded(true)
      draw()
    }
    img.src = getSnapshotUrl(cameraId) + '?t=' + Date.now()

    getRoi(cameraId, module).then(r => {
      if (r.polygon) {
        setSavedPoints(r.polygon)
        setPoints(r.polygon)
      }
    }).catch(() => {})
  }, [cameraId, module])

  useEffect(() => {
    if (loaded) draw()
  }, [points, savedPoints, loaded, drawing])

  const draw = () => {
    const canvas = canvasRef.current
    const img = imgRef.current
    if (!canvas || !img) return

    canvas.width = img.naturalWidth
    canvas.height = img.naturalHeight
    const ctx = canvas.getContext('2d')!
    ctx.drawImage(img, 0, 0)

    const displayPoints = drawing ? points : (savedPoints || [])
    if (displayPoints.length === 0) return

    const color = module === 'reception' ? '#00ffd0' : '#ffcc00'

    // Draw polygon
    const toPixel = (pt: number[]) => [
      pt[0] / 100 * canvas.width,
      pt[1] / 100 * canvas.height,
    ]

    ctx.beginPath()
    const first = toPixel(displayPoints[0])
    ctx.moveTo(first[0], first[1])
    for (let i = 1; i < displayPoints.length; i++) {
      const p = toPixel(displayPoints[i])
      ctx.lineTo(p[0], p[1])
    }
    if (!drawing || displayPoints.length >= 3) ctx.closePath()

    ctx.fillStyle = color + '22'
    ctx.fill()
    ctx.strokeStyle = color
    ctx.lineWidth = 3
    ctx.stroke()

    // Draw points
    for (const pt of displayPoints) {
      const [px, py] = toPixel(pt)
      ctx.beginPath()
      ctx.arc(px, py, 6, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
      ctx.strokeStyle = '#000'
      ctx.lineWidth = 2
      ctx.stroke()
    }

    // Label
    ctx.font = 'bold 16px sans-serif'
    ctx.fillStyle = color
    ctx.fillText(module.toUpperCase() + ' ROI', first[0], first[1] - 12)
  }

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawing) return
    const canvas = canvasRef.current!
    const rect = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const scaleY = canvas.height / rect.height
    const x = ((e.clientX - rect.left) * scaleX) / canvas.width * 100
    const y = ((e.clientY - rect.top) * scaleY) / canvas.height * 100
    setPoints(prev => [...prev, [Math.round(x * 100) / 100, Math.round(y * 100) / 100]])
  }

  const handleDoubleClick = () => {
    if (drawing && points.length >= 3) {
      handleSave()
    }
  }

  const handleSave = async () => {
    if (points.length < 3) return
    setSaving(true)
    try {
      await saveRoi(cameraId, module, points)
      setSavedPoints(points)
      setDrawing(false)
      onSaved?.()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-sm font-medium ${module === 'reception' ? 'text-cyan-400' : 'text-yellow-400'}`}>
          {module === 'reception' ? 'Reception' : 'Crowd'} ROI
        </span>
        {!drawing ? (
          <button
            onClick={() => { setDrawing(true); setPoints([]) }}
            className="flex items-center gap-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-2 py-1 rounded"
          >
            <Pencil className="w-3 h-3" /> {savedPoints ? 'Redraw' : 'Draw'}
          </button>
        ) : (
          <>
            <button
              onClick={() => setPoints([])}
              className="flex items-center gap-1 text-xs bg-gray-800 hover:bg-gray-700 text-red-400 px-2 py-1 rounded"
            >
              <Trash2 className="w-3 h-3" /> Clear
            </button>
            <button
              onClick={handleSave}
              disabled={points.length < 3 || saving}
              className="flex items-center gap-1 text-xs bg-cyan-600 hover:bg-cyan-700 text-white px-2 py-1 rounded disabled:opacity-50"
            >
              <Check className="w-3 h-3" /> {saving ? 'Saving...' : 'Save'}
            </button>
            <span className="text-xs text-gray-500">
              Click to add points. Double-click to finish. ({points.length} points)
            </span>
          </>
        )}
      </div>
      <canvas
        ref={canvasRef}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        className={`w-full rounded-lg border border-gray-700 ${drawing ? 'cursor-crosshair' : 'cursor-default'}`}
        style={{ maxHeight: '400px', objectFit: 'contain' }}
      />
    </div>
  )
}
