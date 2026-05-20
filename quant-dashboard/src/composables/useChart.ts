import { ref, type Ref } from 'vue'
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type LineData,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts'
import type { TimeSeriesResponse, TradeMarker } from '@/types'

export function useChart(containerRef: Ref<HTMLElement | null>) {
  const chart = ref<IChartApi | null>(null)
  let candleSeries: ISeriesApi<'Candlestick'> | null = null
  let zscoreSeries: ISeriesApi<'Line'> | null = null
  let markersPlugin: ReturnType<typeof createSeriesMarkers> | null = null

  function ensureChart() {
    if (chart.value) return true
    if (!containerRef.value) return false
    const el = containerRef.value
    if (el.clientWidth === 0 || el.clientHeight === 0) return false

    chart.value = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#1a1a2e' },
        textColor: '#d1d5db',
      },
      grid: {
        vertLines: { color: '#2a2a3e' },
        horzLines: { color: '#2a2a3e' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#3a3a4e' },
      timeScale: {
        borderColor: '#3a3a4e',
        timeVisible: true,
        secondsVisible: false,
      },
    })

    candleSeries = chart.value.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      wickUpColor: '#22c55e',
    })
    return true
  }

  function setOhlcvData(ts: TimeSeriesResponse | null) {
    if (!ts || ts.data.length === 0) return
    if (!ensureChart() || !candleSeries) return

    const data: CandlestickData[] = ts.data.map((row) => ({
      time: Math.floor(new Date(row[0] as string).getTime() / 1000) as any,
      open: Number(row[1]),
      high: Number(row[2]),
      low: Number(row[3]),
      close: Number(row[4]),
    }))
    candleSeries.setData(data)
    chart.value?.timeScale().fitContent()
  }

  function setZscoreOverlay(ts: TimeSeriesResponse | null) {
    if (!ensureChart()) return
    if (zscoreSeries) {
      chart.value!.removeSeries(zscoreSeries)
      zscoreSeries = null
    }
    if (!ts || ts.data.length === 0) return

    zscoreSeries = chart.value!.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 1,
      priceScaleId: 'zscore',
      title: 'Z-Score',
    })
    chart.value!.priceScale('zscore').applyOptions({
      scaleMargins: { top: 0.7, bottom: 0 },
    })

    const data: LineData[] = ts.data.map((row) => ({
      time: Math.floor(new Date(row[0] as string).getTime() / 1000) as any,
      value: Number(row[1]),
    }))
    zscoreSeries.setData(data)
  }

  function setTradeMarkers(trades: TradeMarker[]) {
    if (!candleSeries) return
    if (markersPlugin) {
      markersPlugin.detach()
      markersPlugin = null
    }
    if (trades.length === 0) return

    const markers = trades.flatMap((t) => [
      {
        time: Math.floor(new Date(t.open_date).getTime() / 1000) as any,
        position: 'belowBar' as const,
        color: '#22c55e',
        shape: 'arrowUp' as const,
        text: `Buy ${t.open_rate.toFixed(2)}`,
      },
      {
        time: Math.floor(new Date(t.close_date).getTime() / 1000) as any,
        position: 'aboveBar' as const,
        color: t.profit_pct >= 0 ? '#22c55e' : '#ef4444',
        shape: 'arrowDown' as const,
        text: `${t.profit_pct >= 0 ? '+' : ''}${(t.profit_pct * 100).toFixed(1)}%`,
      },
    ])
    markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0))
    markersPlugin = createSeriesMarkers(candleSeries, markers)
  }

  function dispose() {
    chart.value?.remove()
    chart.value = null
    candleSeries = null
    zscoreSeries = null
    markersPlugin = null
  }

  return { chart, setOhlcvData, setZscoreOverlay, setTradeMarkers, dispose }
}
