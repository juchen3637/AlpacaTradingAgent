/* TradingView Lightweight Charts renderer for Dash.
 *
 * Charts are mounted into divs with a known id, and updated by a clientside
 * Dash callback that calls window.lwcRender(divId, payload). The payload
 * matches the dict produced by webui/utils/charts_lwc.py.
 *
 * The library is loaded once on first call from a CDN; subsequent calls
 * await the same promise.
 */

(function () {
  const LWC_VERSION = "4.2.3";
  const LWC_CDN =
    "https://unpkg.com/lightweight-charts@" +
    LWC_VERSION +
    "/dist/lightweight-charts.standalone.production.js";

  // divId → { chart, candleSeries, volumeSeries }
  const _instances = new Map();
  let _libPromise = null;

  function _loadLib() {
    if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
    if (_libPromise) return _libPromise;
    _libPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = LWC_CDN;
      script.async = true;
      script.onload = () => resolve(window.LightweightCharts);
      script.onerror = () => reject(new Error("Failed to load lightweight-charts"));
      document.head.appendChild(script);
    });
    return _libPromise;
  }

  function _create(host, payload, LightweightCharts) {
    while (host.firstChild) host.removeChild(host.firstChild);

    const chartOptions = Object.assign(
      {
        autoSize: true,
        layout: {
          background: { type: "solid", color: "#0F172A" },
          textColor: "#CBD5E1",
        },
        grid: {
          vertLines: { color: "rgba(148, 163, 184, 0.1)" },
          horzLines: { color: "rgba(148, 163, 184, 0.1)" },
        },
        crosshair: { mode: 1 },
        rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.2)" },
        timeScale: {
          borderColor: "rgba(148, 163, 184, 0.2)",
          timeVisible: true,
          secondsVisible: false,
        },
      },
      (payload && payload.chartOptions) || {}
    );

    const chart = LightweightCharts.createChart(host, chartOptions);

    const candleOpts = (payload && payload.seriesOptions && payload.seriesOptions[0]) || {};
    const candleSeries = chart.addCandlestickSeries(candleOpts);

    const volOpts = (payload && payload.seriesOptions && payload.seriesOptions[1]) || {};
    const volumeSeries = chart.addHistogramSeries(volOpts);

    return { chart, candleSeries, volumeSeries };
  }

  function _applyPriceLines(series, priceLines) {
    // Each series instance keeps its own list of price-line handles, so we
    // drop them all and recreate to avoid drift on re-render.
    if (!series._lwcPriceLines) series._lwcPriceLines = [];
    for (const handle of series._lwcPriceLines) {
      try {
        series.removePriceLine(handle);
      } catch (e) {
        /* ignore */
      }
    }
    series._lwcPriceLines = [];
    for (const line of priceLines || []) {
      try {
        series._lwcPriceLines.push(series.createPriceLine(line));
      } catch (e) {
        /* ignore individual line failures */
      }
    }
  }

  function _render(divId, payload) {
    const host = document.getElementById(divId);
    if (!host) return;
    if (!payload) return;

    _loadLib()
      .then((LightweightCharts) => {
        let inst = _instances.get(divId);
        let isFirstRender = false;
        if (!inst || !host.contains(inst.chart.chartElement && inst.chart.chartElement())) {
          inst = _create(host, payload, LightweightCharts);
          _instances.set(divId, inst);
          isFirstRender = true;
        }
        const seriesData = payload.seriesData || [[], []];
        const candles = seriesData[0] || [];
        const volume = seriesData[1] || [];
        inst.candleSeries.setData(candles);
        inst.volumeSeries.setData(volume);

        const priceLines = payload.seriesPriceLines || [[], []];
        _applyPriceLines(inst.candleSeries, priceLines[0] || []);

        const markers = payload.seriesMarkers || [[], []];
        inst.candleSeries.setMarkers(markers[0] || []);

        // Fit only on the first render — subsequent refreshes preserve the
        // user's pan/zoom. setData on existing series keeps the visible range.
        if (isFirstRender && candles.length > 0) {
          inst.chart.timeScale().fitContent();
        }
      })
      .catch((err) => {
        console.error("[lwc.js] load/render failed:", err);
      });
  }

  window.lwcRender = _render;
})();
