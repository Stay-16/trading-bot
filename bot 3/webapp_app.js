const state = {
  timeframe: "1m",
  category: "all",
  markets: [],
  filteredMarkets: [],
  selectedAssetId: null,
  lastAnalysis: null,
  liveSocket: null,
  chart: null,
  candleSeries: null,
  pairSearch: "",
  liveRetryTimer: null,
  liveRetryCount: 0,
  livePollTimer: null,
};

const els = {
  connectionBadge: document.getElementById("connectionBadge"),
  balanceBadge: document.getElementById("balanceBadge"),
  updatedAt: document.getElementById("updatedAt"),
  timeframeSelect: document.getElementById("timeframeSelect"),
  categorySelect: document.getElementById("categorySelect"),
  pairSearchInput: document.getElementById("pairSearchInput"),
  refreshButton: document.getElementById("refreshButton"),
  scanButton: document.getElementById("scanButton"),
  marketBoard: document.getElementById("marketBoard"),
  topSetups: document.getElementById("topSetups"),
  headlineSignal: document.getElementById("headlineSignal"),
  headlineConfidence: document.getElementById("headlineConfidence"),
  headlinePair: document.getElementById("headlinePair"),
  headlineDirection: document.getElementById("headlineDirection"),
  headlineBias: document.getElementById("headlineBias"),
  headlineRisk: document.getElementById("headlineRisk"),
  headlineScore: document.getElementById("headlineScore"),
  sentimentValue: document.getElementById("sentimentValue"),
  sentimentLabel: document.getElementById("sentimentLabel"),
  sentimentMeter: document.getElementById("sentimentMeter"),
  detailMethod: document.getElementById("detailMethod"),
  analysisCards: document.getElementById("analysisCards"),
  decisionReasons: document.getElementById("decisionReasons"),
  chartMeta: document.getElementById("chartMeta"),
  miniChart: document.getElementById("miniChart"),
  tradeCallButton: document.getElementById("tradeCallButton"),
  tradePutButton: document.getElementById("tradePutButton"),
  tradeStatus: document.getElementById("tradeStatus"),
};

function safeFetchJson(url) {
  return fetch(url).then(async (response) => {
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Request failed: ${response.status}`);
    }
    return response.json();
  });
}

function reportUiError(message) {
  const text = String(message || "Unknown UI error");
  console.error(text);
  if (els.tradeStatus) {
    els.tradeStatus.textContent = text;
  }
  if (els.analysisCards) {
    els.analysisCards.innerHTML = `<div class="empty-card">${text}</div>`;
  }
}

function directionLabel(direction) {
  return direction === "call" ? "BUY / CALL" : direction === "put" ? "SELL / PUT" : "WAIT";
}

function recommendationDirectionLabel(direction) {
  return direction === "call" ? "CALL" : direction === "put" ? "PUT" : "WAIT";
}

function sentimentText(value) {
  if (value >= 60) return "Bullish Market";
  if (value <= 40) return "Bearish Market";
  return "Mixed Market";
}

function formatBalance(value) {
  return typeof value === "number" ? `$${value.toFixed(2)}` : "--";
}

function formatPercent(value) {
  return typeof value === "number" ? `${Math.round(value)}%` : "--";
}

function formatPrice(value) {
  return typeof value === "number" ? value.toFixed(5) : "--";
}

function formatPillClass(value) {
  return ["call", "put", "neutral", "low", "medium", "high"].includes(value) ? value : "neutral";
}

function formatConfidenceWithDirection(confidence, direction) {
  const percent = formatPercent(confidence);
  const label = recommendationDirectionLabel(direction);
  return percent === "--" ? label : `${percent} ${label}`;
}

function filterMarkets() {
  const query = state.pairSearch.trim().toLowerCase();
  if (!query) {
    state.filteredMarkets = [...state.markets];
    return;
  }

  state.filteredMarkets = state.markets.filter((item) => {
    const haystack = [
      item.display_name,
      item.pair_key,
      item.quotex_symbol,
      item.symbol,
      item.market_type,
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function setTradeButtonsEnabled(enabled) {
  els.tradeCallButton.disabled = !enabled;
  els.tradePutButton.disabled = !enabled;
}

function updateHero(analysis) {
  const direction = analysis.direction || "neutral";
  els.headlineSignal.className = `headline-card ${direction}`;
  els.headlineSignal.querySelector(".headline-title").textContent = analysis.asset.display_name;
  els.headlineSignal.querySelector("h2").textContent = `${directionLabel(direction)} with ${analysis.analysis_method}`;
  els.headlineConfidence.textContent = formatConfidenceWithDirection(analysis.confidence, direction);
  els.headlinePair.textContent = analysis.asset.display_name;
  els.headlineDirection.textContent = directionLabel(direction);
  els.headlineBias.textContent = recommendationDirectionLabel(direction);
  els.headlineRisk.textContent = (analysis.risk_level || "--").toUpperCase();
  els.headlineScore.textContent = formatPercent(analysis.decision_score);
}

function renderReasons(reasons) {
  if (!reasons || reasons.length === 0) {
    els.decisionReasons.innerHTML = '<div class="empty-card">No decision reasons were returned for this setup.</div>';
    return;
  }

  els.decisionReasons.innerHTML = reasons.map((reason) => {
    const title = String(reason).split(":")[0] || "Reason";
    return `
      <article class="reason-card">
        <h4>${title}</h4>
        <p>${reason}</p>
      </article>
    `;
  }).join("");
}

function renderAnalysisCards(analysis) {
  const traditional = analysis.traditional || {};
  const lstm = analysis.lstm_signal || {};
  const asset = analysis.asset || {};
  const insights = analysis.market_insights || {};
  const modelWeights = Object.entries(analysis.model_weights || {})
    .map(([name, value]) => `${name}: ${Number(value).toFixed(2)}`)
    .join(" | ") || "uniform";

  els.detailMethod.textContent = analysis.degraded
    ? `degraded | ${analysis.analysis_method || "unknown"}`
    : (analysis.analysis_method || "unknown");

  els.analysisCards.innerHTML = `
    <article class="analysis-card">
      <span>Traditional Signal</span>
      <strong>${directionLabel(traditional.direction)}</strong>
      <p>${traditional.recommendation || "N/A"} | ${formatConfidenceWithDirection(traditional.confidence, traditional.direction)}</p>
    </article>
    <article class="analysis-card">
      <span>LSTM Base Model</span>
      <strong>${directionLabel(lstm.direction)}</strong>
      <p>${lstm.method || "unavailable"} | ${formatConfidenceWithDirection(lstm.confidence, lstm.direction)}</p>
    </article>
    <article class="analysis-card">
      <span>Payout / Asset</span>
      <strong>${formatPercent(asset.payout ?? analysis.live_payout)}</strong>
      <p>${asset.quotex_symbol || "N/A"}</p>
    </article>
    <article class="analysis-card">
      <span>Live Price</span>
      <strong>${formatPrice(analysis.live_price)}</strong>
      <p>Sentiment: ${formatPercent(analysis.live_sentiment)}</p>
    </article>
    <article class="analysis-card full">
      <span>Technical Summary</span>
      <strong>${analysis.candle_pattern || "N/A"}</strong>
      <p>${analysis.technical_summary || "No technical summary available."}</p>
    </article>
    <article class="analysis-card full">
      <span>Models</span>
      <strong>${(analysis.models_used || []).join(", ") || "No models listed"}</strong>
      <p>${modelWeights}</p>
    </article>
    <article class="analysis-card full">
      <span>Live Status</span>
      <strong>${analysis.degraded ? "Cached / degraded mode" : "Live analysis"}</strong>
      <p>${analysis.degraded_reason || "Live market data and decision stack are available."}</p>
    </article>
    <article class="analysis-card">
      <span>Historical Win Rate</span>
      <strong>${formatPercent(insights.historical_win_rate)}</strong>
      <p>${insights.pattern_confidence || "N/A"} confidence</p>
    </article>
    <article class="analysis-card">
      <span>Total Learned Trades</span>
      <strong>${analysis.performance?.total_trades ?? 0}</strong>
      <p>Profit factor: ${analysis.performance?.profit_factor ?? 0}</p>
    </article>
  `;
}

function initChart() {
  if (state.chart) {
    state.chart.remove();
  }

  try {
    state.chart = LightweightCharts.createChart(els.miniChart, {
      layout: {
        background: { color: "transparent" },
        textColor: "#d7def5",
        fontFamily: "Manrope, sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.06)" },
        horzLines: { color: "rgba(255,255,255,0.06)" },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.08)",
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: "rgba(255,255,255,0.14)" },
        horzLine: { color: "rgba(255,255,255,0.14)" },
      },
      handleScroll: false,
      handleScale: false,
    });

    const seriesOptions = {
      upColor: "#12d189",
      downColor: "#ff6778",
      borderUpColor: "#12d189",
      borderDownColor: "#ff6778",
      wickUpColor: "#12d189",
      wickDownColor: "#ff6778",
    };

    if (typeof state.chart.addCandlestickSeries === "function") {
      state.candleSeries = state.chart.addCandlestickSeries(seriesOptions);
      return;
    }

    if (typeof state.chart.addSeries === "function" && LightweightCharts.CandlestickSeries) {
      state.candleSeries = state.chart.addSeries(LightweightCharts.CandlestickSeries, seriesOptions);
      return;
    }

    throw new Error("Candlestick series API is unavailable in this chart build.");
  } catch (error) {
    console.error("Chart initialization failed:", error);
    state.chart = null;
    state.candleSeries = null;
    els.chartMeta.textContent = "Chart unavailable";
    els.miniChart.innerHTML = '<div class="empty-card">Chart unavailable, but analysis is still active.</div>';
  }
}

function setChartCandles(candles) {
  if (!state.candleSeries) {
    initChart();
  }

  if (!state.candleSeries) {
    return;
  }

  if (!candles || candles.length === 0) {
    state.candleSeries.setData([]);
    els.chartMeta.textContent = "Waiting for live candle stream";
    return;
  }

  const transformed = candles.map((candle, index) => ({
    time: Number(candle.time || index + 1),
    open: Number(candle.open),
    high: Number(candle.high),
    low: Number(candle.low),
    close: Number(candle.close),
  }));

  state.candleSeries.setData(transformed);
  state.chart.timeScale().fitContent();
  els.chartMeta.textContent = `Live candles: ${transformed.length}`;
}

function connectLiveFeed(assetId, timeframe) {
  if (state.liveRetryTimer) {
    clearTimeout(state.liveRetryTimer);
    state.liveRetryTimer = null;
  }
  if (state.livePollTimer) {
    clearInterval(state.livePollTimer);
    state.livePollTimer = null;
  }

  if (state.liveSocket) {
    state.liveSocket.close();
    state.liveSocket = null;
  }

  if (!assetId) {
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${protocol}://${window.location.host}/ws/live-feed?asset_id=${encodeURIComponent(assetId)}&timeframe=${encodeURIComponent(timeframe)}`;
  let socket = null;

  const applyLivePayload = (payload) => {
    if (!payload) {
      return;
    }

    if (payload.error) {
      els.tradeStatus.textContent = payload.error;
      return;
    }

    if (typeof payload.sentiment === "number") {
      els.sentimentValue.textContent = `${Math.round(payload.sentiment)}%`;
      els.sentimentLabel.textContent = sentimentText(payload.sentiment);
      els.sentimentMeter.style.width = `${Math.max(0, Math.min(100, payload.sentiment))}%`;
    }

    if (typeof payload.payout === "number" && state.lastAnalysis) {
      state.lastAnalysis.live_payout = payload.payout;
    }

    if (typeof payload.price === "number" && state.lastAnalysis) {
      state.lastAnalysis.live_price = payload.price;
    }

    setChartCandles(payload.candles || []);
    els.updatedAt.textContent = new Date((payload.timestamp || Date.now() / 1000) * 1000).toLocaleTimeString();
  };

  const startHttpPolling = () => {
    if (state.livePollTimer || assetId !== state.selectedAssetId) {
      return;
    }

    const pollOnce = async () => {
      try {
        const payload = await safeFetchJson(`/api/live-snapshot?asset_id=${encodeURIComponent(assetId)}&timeframe=${encodeURIComponent(timeframe)}`);
        applyLivePayload(payload);
        els.connectionBadge.textContent = "HTTP live polling";
        els.connectionBadge.classList.remove("loading");
      } catch (error) {
        els.tradeStatus.textContent = `Live polling failed: ${error.message}`;
      }
    };

    pollOnce();
    state.livePollTimer = window.setInterval(pollOnce, 2500);
  };

  try {
    socket = new WebSocket(wsUrl);
    state.liveSocket = socket;

    socket.onopen = () => {
      state.liveRetryCount = 0;
      els.connectionBadge.textContent = "Live feed connected";
      els.connectionBadge.classList.remove("loading");
    };

    socket.onmessage = (event) => {
      applyLivePayload(JSON.parse(event.data));
    };

    socket.onerror = () => {
      startHttpPolling();
    };

    socket.onclose = () => {
      if (state.liveSocket === socket) {
        state.liveSocket = null;
      }

      if (assetId !== state.selectedAssetId) {
        return;
      }

      startHttpPolling();
    };
  } catch (error) {
    startHttpPolling();
  }
}

function renderMarkets(items) {
  if (!items || items.length === 0) {
    els.marketBoard.innerHTML = '<div class="empty-card">No matching pairs were found.</div>';
    return;
  }

  els.marketBoard.innerHTML = items.map((item) => `
    <button class="market-item ${item.id === state.selectedAssetId ? "active" : ""}" data-asset-id="${item.id}">
      <div class="pair-badge">
        <span class="pair-dot"></span>
        <div>
          <div>${item.display_name}</div>
          <small>${item.market_type.toUpperCase()}</small>
        </div>
      </div>
      <div class="market-meta">
        <span>Payout</span>
        <strong>${item.payout == null ? "N/A" : formatPercent(item.payout)}</strong>
      </div>
    </button>
  `).join("");

  els.marketBoard.querySelectorAll("[data-asset-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedAssetId = button.dataset.assetId;
      renderMarkets(state.filteredMarkets);
      loadAnalysis();
    });
  });
}

function renderTopSetups(items) {
  if (!items || items.length === 0) {
    els.topSetups.innerHTML = '<div class="empty-card">No strong scanner setups were found on this timeframe.</div>';
    return;
  }

  els.topSetups.innerHTML = items.map((item, index) => `
    <article class="opportunity-card" data-asset-id="${item.asset.id}">
      <div class="opportunity-top">
        <div class="pair-badge">
          <span class="pair-dot"></span>
          <div>
            <div>#${index + 1} ${item.asset.display_name}</div>
            <small>${item.asset.market_type.toUpperCase()}</small>
          </div>
        </div>
        <span class="pill ${formatPillClass(item.direction)}">${directionLabel(item.direction)}</span>
      </div>
      <div class="opportunity-stats">
        <div class="stat-chip"><span>Confidence</span><strong>${formatConfidenceWithDirection(item.confidence, item.direction)}</strong></div>
        <div class="stat-chip"><span>Payout</span><strong>${formatPercent(item.asset.payout)}</strong></div>
        <div class="stat-chip"><span>Trend</span><strong>${item.trend_condition}</strong></div>
      </div>
    </article>
  `).join("");

  els.topSetups.querySelectorAll("[data-asset-id]").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedAssetId = card.dataset.assetId;
      renderMarkets(state.filteredMarkets);
      loadAnalysis();
    });
  });
}

async function loadHealth() {
  const data = await safeFetchJson("/api/health");
  els.connectionBadge.textContent = data.connection || "Unknown";
  els.connectionBadge.classList.remove("loading");
  els.balanceBadge.textContent = `Balance: ${formatBalance(data.balance)}`;
}

async function loadMarkets() {
  const data = await safeFetchJson(`/api/markets?category=${encodeURIComponent(state.category)}`);
  state.markets = data.items || [];
  filterMarkets();

  const selectedStillVisible = state.filteredMarkets.some((item) => item.id === state.selectedAssetId);
  if (!selectedStillVisible) {
    state.selectedAssetId = state.filteredMarkets.length > 0 ? state.filteredMarkets[0].id : null;
  }

  renderMarkets(state.filteredMarkets);
}

async function loadScanner() {
  els.topSetups.innerHTML = '<div class="loading-state">Scanning the live Quotex board...</div>';
  try {
    const data = await safeFetchJson(`/api/top-setups?timeframe=${encodeURIComponent(state.timeframe)}&category=${encodeURIComponent(state.category)}&limit=3`);
    renderTopSetups(data.items || []);

    const bullishCount = (data.items || []).filter((item) => item.direction === "call").length;
    const total = Math.max(1, (data.items || []).length);
    const marketValue = Math.round((bullishCount / total) * 100);
    els.sentimentValue.textContent = `${marketValue}%`;
    els.sentimentLabel.textContent = sentimentText(marketValue);
    els.sentimentMeter.style.width = `${marketValue}%`;
    els.updatedAt.textContent = new Date().toLocaleTimeString();
  } catch (error) {
    els.topSetups.innerHTML = `<div class="empty-card">${error.message}</div>`;
    els.sentimentValue.textContent = "--%";
    els.sentimentLabel.textContent = "Scanner unavailable";
    els.sentimentMeter.style.width = "0%";
  }
}

async function loadAnalysis() {
  if (!state.selectedAssetId) {
    state.lastAnalysis = null;
    els.analysisCards.innerHTML = '<div class="empty-card">Choose a pair from the market board to open the analysis.</div>';
    renderReasons([]);
    setChartCandles([]);
    setTradeButtonsEnabled(false);
    els.tradeStatus.textContent = "Choose a pair to start the live recommendation.";
    return;
  }

  els.analysisCards.innerHTML = '<div class="loading-state">Running layered analysis...</div>';
  try {
    const data = await safeFetchJson(`/api/analyze?asset_id=${encodeURIComponent(state.selectedAssetId)}&timeframe=${encodeURIComponent(state.timeframe)}`);
    state.lastAnalysis = data;
    updateHero(data);
    renderAnalysisCards(data);
    renderReasons(data.decision_reasons || []);
    setChartCandles(data.price_series || []);
    connectLiveFeed(state.selectedAssetId, state.timeframe);
    els.updatedAt.textContent = new Date().toLocaleTimeString();

    if (typeof data.live_sentiment === "number") {
      els.sentimentValue.textContent = `${Math.round(data.live_sentiment)}%`;
      els.sentimentLabel.textContent = sentimentText(data.live_sentiment);
      els.sentimentMeter.style.width = `${Math.max(0, Math.min(100, data.live_sentiment))}%`;
    }

    const canTrade = ["call", "put"].includes(data.direction) && (Number(data.confidence || 0) > 0);
    setTradeButtonsEnabled(canTrade);
    els.tradeStatus.textContent = canTrade
      ? `Ready to open a ${directionLabel(data.direction)} trade on ${data.asset.display_name}.`
      : (data.degraded_reason || "Direct execution is disabled until a live CALL or PUT setup is available.");
  } catch (error) {
    state.lastAnalysis = null;
    setTradeButtonsEnabled(false);
    renderReasons([]);
    setChartCandles([]);
    els.detailMethod.textContent = "analysis failed";
    els.analysisCards.innerHTML = `<div class="empty-card">${error.message}</div>`;
    els.tradeStatus.textContent = `Analysis failed: ${error.message}`;
  }
}

async function refreshAll() {
  const healthResult = await Promise.allSettled([loadHealth(), loadMarkets()]);
  const failedCore = healthResult.find((result) => result.status === "rejected");
  if (failedCore) {
    const error = failedCore.reason;
    console.error(error);
    els.marketBoard.innerHTML = `<div class="empty-card">${error.message}</div>`;
    els.tradeStatus.textContent = error.message;
    return;
  }

  await loadAnalysis();
  await Promise.allSettled([loadScanner()]);
}

async function executeTrade(direction) {
  if (!state.lastAnalysis) {
    return;
  }

  const userId = window.Telegram?.WebApp?.initDataUnsafe?.user?.id || 0;
  els.tradeStatus.textContent = `Submitting ${direction.toUpperCase()} trade...`;

  try {
    const response = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_id: state.lastAnalysis.asset.id,
        timeframe: state.timeframe,
        direction,
        user_id: userId,
        confidence: state.lastAnalysis.confidence,
      }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Trade execution failed");
    }

    els.tradeStatus.textContent = `Trade opened: ${payload.pair} ${payload.direction.toUpperCase()} | $${payload.amount} | ID ${payload.trade_id}`;
  } catch (error) {
    els.tradeStatus.textContent = error.message;
  }
}

function handlePairSearch(event) {
  state.pairSearch = event.target.value || "";
  filterMarkets();

  const selectedStillVisible = state.filteredMarkets.some((item) => item.id === state.selectedAssetId);
  if (!selectedStillVisible) {
    state.selectedAssetId = state.filteredMarkets.length > 0 ? state.filteredMarkets[0].id : null;
  }

  renderMarkets(state.filteredMarkets);
}

function initTelegramTheme() {
  const app = window.Telegram?.WebApp;
  if (!app) return;
  app.ready();
  app.expand();
}

window.addEventListener("resize", () => {
  if (state.chart) {
    state.chart.applyOptions({ width: els.miniChart.clientWidth });
  }
});

window.addEventListener("error", (event) => {
  reportUiError(`UI error: ${event.message}`);
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason?.message || event.reason || "Unhandled promise rejection";
  reportUiError(`UI error: ${reason}`);
});

els.timeframeSelect.addEventListener("change", async (event) => {
  state.timeframe = event.target.value;
  await loadScanner();
  await loadAnalysis();
});

els.categorySelect.addEventListener("change", async (event) => {
  state.category = event.target.value;
  state.selectedAssetId = null;
  await loadMarkets();
  await loadScanner();
  await loadAnalysis();
});

els.pairSearchInput.addEventListener("input", handlePairSearch);
els.refreshButton.addEventListener("click", refreshAll);
els.scanButton.addEventListener("click", loadScanner);
els.tradeCallButton.addEventListener("click", () => executeTrade("call"));
els.tradePutButton.addEventListener("click", () => executeTrade("put"));

initTelegramTheme();
setTradeButtonsEnabled(false);

try {
  initChart();
} catch (error) {
  reportUiError(`Initial chart boot failed: ${error.message || error}`);
}

refreshAll().catch((error) => {
  reportUiError(`Startup failed: ${error.message || error}`);
});
