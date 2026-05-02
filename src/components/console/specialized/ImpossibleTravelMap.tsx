import { useEffect, useMemo } from 'react'
import { MapContainer, Marker, Polyline, TileLayer, useMap } from 'react-leaflet'
import L from 'leaflet'
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'
import 'leaflet/dist/leaflet.css'

type Point = { lat: number; lon: number; label?: string }

function useFixLeafletIcons() {
  useEffect(() => {
    L.Icon.Default.mergeOptions({
      iconUrl: markerIcon,
      iconRetinaUrl: markerIcon2x,
      shadowUrl: markerShadow,
    })
  }, [])
}

function FitBounds({ a, b }: { a: Point; b: Point }) {
  const map = useMap()
  useEffect(() => {
    const bounds = L.latLngBounds([a.lat, a.lon], [b.lat, b.lon])
    map.fitBounds(bounds, { padding: [28, 28], maxZoom: 8 })
  }, [map, a.lat, a.lon, b.lat, b.lon])
  return null
}

type Props = {
  prior: Point
  current: Point
}

export function ImpossibleTravelMap({ prior, current }: Props) {
  useFixLeafletIcons()
  const center = useMemo(
    () => [(prior.lat + current.lat) / 2, (prior.lon + current.lon) / 2] as [number, number],
    [prior.lat, prior.lon, current.lat, current.lon],
  )

  return (
    <div className="relative z-0 mt-3 h-[200px] w-full overflow-hidden rounded-md border border-zinc-800 bg-zinc-950">
      <MapContainer center={center} zoom={3} className="h-full w-full" scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; CARTO'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
        />
        <FitBounds a={prior} b={current} />
        <Polyline
          positions={[
            [prior.lat, prior.lon],
            [current.lat, current.lon],
          ]}
          pathOptions={{ color: '#f43f5e', weight: 3, opacity: 0.85 }}
        />
        <Marker position={[prior.lat, prior.lon]}>
          {/* Popup optional — keep density */}
        </Marker>
        <Marker position={[current.lat, current.lon]} />
      </MapContainer>
      <div className="pointer-events-none absolute bottom-1 right-1 rounded bg-black/55 px-1.5 py-0.5 text-[8px] text-zinc-400">
        Map
      </div>
    </div>
  )
}
