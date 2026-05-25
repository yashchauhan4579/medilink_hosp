import { useEffect, useRef, useState } from 'react'
import { connectFeed } from '../lib/ws'

interface Props {
  cameraId: number
  className?: string
  showMeta?: boolean
}

export default function LiveFeed({ cameraId, className = '', showMeta = false }: Props) {
  const imgRef = useRef<HTMLImageElement>(null)
  const [meta, setMeta] = useState<any>(null)
  const urlRef = useRef<string | null>(null)

  useEffect(() => {
    const unsub = connectFeed(cameraId, (blob, m) => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
      const url = URL.createObjectURL(blob)
      urlRef.current = url
      if (imgRef.current) imgRef.current.src = url
      if (showMeta) setMeta(m)
    })

    return () => {
      unsub()
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    }
  }, [cameraId, showMeta])

  return (
    <div className="relative">
      <img ref={imgRef} className={className} alt="Live feed" />
      {showMeta && meta && (
        <div className="absolute bottom-0 left-0 right-0 bg-black/70 px-3 py-1.5 flex gap-4 text-xs">
          <span className="text-cyan-400">Detections: {meta.detections}</span>
          <span className="text-green-400">Reception: {meta.reception_heads}</span>
          <span className="text-yellow-400">Crowd: {meta.crowd_heads}</span>
        </div>
      )}
    </div>
  )
}
