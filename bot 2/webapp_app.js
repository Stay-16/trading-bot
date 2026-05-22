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
  chartPriceLines: [],
  pairSearch: "",
  liveRetryTimer: null,
  liveRetryCount: 0,
  livePollTimer: null,
  analysisPollTimer: null,
  liveFeedKey: null,
  tradeSubmitting: false,
  analysisRequestId: 0,
  marketsRequestId: 0,
  scannerRequestId: 0,
  systemFeed: [],
};
const PREFER_HTTP_LIVE_FEED = true;
const API_TOKEN_STORAGE_KEY = "quotex_ai_desk_api_token";
const USER_ID_STORAGE_KEY = "quotex_ai_desk_user_id";

const els = {
  connectionBadge: document.getElementById("connectionBadge"),
  balanceBadge: document.getElementById("balanceBadge"),
  clock: document.getElementById("clock"),
  updatedAt: document.getElementById("updatedAt"),
  timeframeSelect: document.getElementById("timeframeSelect"),
  categorySelect: document.getElementById("categorySelect"),
  pairSearchInput: document.getElementById("pairSearchInput"),
  refreshButton: document.getElementById("refreshButton"),
  apiTokenInput: document.getElementById("apiTokenInput"),
  saveApiTokenButton: document.getElementById("saveApiTokenButton"),
  apiTokenStatus: document.getElementById("apiTokenStatus"),
  userIdInput: document.getElementById("userIdInput"),
  saveUserIdButton: document.getElementById("saveUserIdButton"),
  userIdStatus: document.getElementById("userIdStatus"),
  scanButton: document.getElementById("scanButton"),
  marketBoard: document.getElementById("marketBoard"),
  topSetups: document.getElementById("topSetups"),
  tradeJournal: document.getElementById("tradeJournal"),
  journalAnalytics: document.getElementById("journalAnalytics"),
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
  liveAnalysisFlow: document.getElementById("liveAnalysisFlow"),
  decisionReasons: document.getElementById("decisionReasons"),
  chartMeta: document.getElementById("chartMeta"),
  miniChart: document.getElementById("miniChart"),
  tradeCallButton: document.getElementById("tradeCallButton"),
  tradePutButton: document.getElementById("tradePutButton"),
  tradeStatus: document.getElementById("tradeStatus"),
  systemFeed: document.getElementById("systemFeed"),
  topMetricWinRate: document.getElementById("topMetricWinRate"),
  topMetricTrades: document.getElementById("topMetricTrades"),
  topMetricProfit: document.getElementById("topMetricProfit"),
  topMetricConfidence: document.getElementById("topMetricConfidence"),
  summaryMarketCount: document.getElementById("summaryMarketCount"),
  summarySelectedAsset: document.getElementById("summarySelectedAsset"),
  summaryScannerStatus: document.getElementById("summaryScannerStatus"),
};

function safeFetchJson(url, options = {}) {
  const controller = new AbortController();
  const timeoutMs = Number(options.timeoutMs || 12000);
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const headers = new Headers(options.headers || {});
  const apiToken = getApiToken();
  if (apiToken) {
    headers.set("X-API-Key", apiToken);
  }

  return fetch(url, { ...options, headers, signal: controller.signal }).then(async (response) => {
    if (!response.ok) {
      const contentType = response.headers.get("content-type") || "";
      let text = "";
      try {
        if (contentType.includes("application/json")) {
          const payload = await response.json();
          text = payload.detail || payload.message || JSON.stringify(payload);
        } else {
          text = await response.text();
        }
      } catch (error) {
        text = "";
      }
      throw new Error(text || `Request failed: ${response.status}`);
    }
    return response.json();
  }).catch((error) => {
    if (error.name === "AbortError") {
      throw new Error("Request timed out. Please try again.");
    }
    throw error;
  }).finally(() => {
    clearTimeout(timeoutId);
  });
}

function getApiToken() {
  const queryToken = new URLSearchParams(window.location.search).get("api_token");
  if (queryToken) {
    window.localStorage.setItem(API_TOKEN_STORAGE_KEY, queryToken);
    return queryToken;
  }
  return window.localStorage.getItem(API_TOKEN_STORAGE_KEY) || "";
}

function renderApiTokenState() {
  const apiToken = getApiToken();
  if (els.apiTokenInput && apiToken) {
    els.apiTokenInput.value = apiToken;
  }
  if (els.apiTokenStatus) {
    els.apiTokenStatus.textContent = apiToken
      ? "API token saved in this browser."
      : "Set your API token once if your backend requires it.";
  }
}

function getConfiguredUserId() {
  const queryUserId = new URLSearchParams(window.location.search).get("user_id");
  if (queryUserId && Number(queryUserId) > 0) {
    window.localStorage.setItem(USER_ID_STORAGE_KEY, String(Number(queryUserId)));
    return Number(queryUserId);
  }

  const telegramUserId = window.Telegram?.WebApp?.initDataUnsafe?.user?.id;
  if (telegramUserId && Number(telegramUserId) > 0) {
    return Number(telegramUserId);
  }

  const savedUserId = window.localStorage.getItem(USER_ID_STORAGE_KEY) || "";
  return Number(savedUserId) > 0 ? Number(savedUserId) : 0;
}

function renderUserIdState() {
  const userId = getConfiguredUserId();
  if (els.userIdInput && userId > 0) {
    els.userIdInput.value = String(userId);
  }
  if (els.userIdStatus) {
    els.userIdStatus.textContent = userId > 0
      ? `Current user id: ${userId}`
      : "Set your user id once before opening trades.";
  }
}

function setText(element, value) {
  if (element) {
    element.textContent = value;
  }
}

function updateClock() {
  if (!els.clock) {
    return;
  }
  els.clock.textContent = new Date().toLocaleTimeString();
}

function renderSystemFeed() {
  if (!els.systemFeed) {
    return;
  }

  if (!state.systemFeed.length) {
    els.systemFeed.innerHTML = '<div class="empty-card">System events will appear here as the dashboard updates.</div>';
    return;
  }

  els.systemFeed.innerHTML = state.systemFeed.map((item) => `
    <div class="feed-item">
      <span class="feed-dot ${item.tone || "blue"}"></span>
      <span class="feed-time">${item.time}</span>
      <span>${item.message}</span>
    </div>
  `).join("");
}

function pushSystemFeed(message, tone = "blue") {
  const text = String(message || "").trim();
  if (!text) {
    return;
  }

  state.systemFeed.unshift({
    message: text,
    tone,
    time: new Date().toLocaleTimeString(),
  });
  state.systemFeed = state.systemFeed.slice(0, 8);
  renderSystemFeed();
}

function updateSummarySelectedAsset(label) {
  setText(els.summarySelectedAsset, label || "--");
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
  pushSystemFeed(text, "red");
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

function formatHealthClass(score) {
  if (score >= 75) return "call";
  if (score >= 50) return "medium";
  return "put";
}

function formatConfidenceWithDirection(confidence, direction) {
  if (typeof confidence === "number" && confidence <= 0) {
    return "WAIT";
  }
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
  const disabled = !enabled || state.tradeSubmitting;
  els.tradeCallButton.disabled = disabled;
  els.tradePutButton.disabled = disabled;
}

function setEntryWatchButtons() {}

function stopAnalysisPolling() {
  if (state.analysisPollTimer) {
    clearInterval(state.analysisPollTimer);
    state.analysisPollTimer = null;
  }
}

function stopLiveFeed() {
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
}

function startAnalysisPolling() {
  stopAnalysisPolling();
  if (!state.selectedAssetId) {
    return;
  }
  const currentAssetId = state.selectedAssetId;
  const currentTimeframe = state.timeframe;
  state.analysisPollTimer = window.setInterval(() => {
    if (state.selectedAssetId !== currentAssetId || state.timeframe !== currentTimeframe || state.tradeSubmitting) {
      return;
    }
    loadAnalysis({ silent: true });
  }, 6000);
}

function updateHero(analysis) {
  const direction = analysis.direction || "neutral";
  els.headlineSignal.className = `headline-card ${direction}`;
  els.headlineSignal.querySelector(".headline-title").textContent = analysis.asset.display_name;
  els.headlineSignal.querySelector("h1").textContent = `${directionLabel(direction)} with ${analysis.analysis_method}`;
  els.headlineConfidence.textContent = formatConfidenceWithDirection(analysis.confidence, direction);
  els.headlinePair.textContent = analysis.asset.display_name;
  els.headlineDirection.textContent = directionLabel(direction);
  els.headlineBias.textContent = recommendationDirectionLabel(direction);
  els.headlineRisk.textContent = (analysis.risk_level || "--").toUpperCase();
  els.headlineScore.textContent = formatPercent(analysis.decision_score);
  setText(els.topMetricConfidence, formatPercent(analysis.confidence));
  updateSummarySelectedAsset(analysis.asset.display_name || "--");
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
        <strong>${title}</strong>
        <p>${reason}</p>
      </article>
    `;
  }).join("");
}

function renderLiveAnalysis(analysis) {
  const steps = analysis?.live_analysis_steps || [];
  const voting = analysis?.ai_voting || {};
  const sentiment = analysis?.live_sentiment;

  if (!steps.length) {
    els.liveAnalysisFlow.innerHTML = '<div class="empty-card">The live analysis flow will appear here after you choose a pair.</div>';
    return;
  }

  const badgeClass = voting.grade === "gold"
    ? "call"
    : voting.grade === "watch"
      ? "medium"
      : "put";

  els.liveAnalysisFlow.innerHTML = `
    <article class="analysis-card full">
      <span>AI Voting</span>
      <strong>${voting.label || "Wait"}</strong>
      <p>${voting.summary || "No scoring summary yet."} ${typeof sentiment === "number" ? `Live sentiment: ${Math.round(sentiment)}%.` : ""}</p>
    </article>
    ${steps.map((step) => `
      <article class="pipeline-card ${step.status || "blocked"}">
        <div class="pipeline-mark">${step.status === "passed" ? "OK" : step.status === "warning" ? "..." : "NO"}</div>
        <div>
          <div class="pipeline-head">
            <strong>${step.headline || "Pending"}</strong>
            <span class="direction-pill ${badgeClass}">${step.label || "Step"}</span>
          </div>
          <p>${step.detail || "No detail available yet."}</p>
        </div>
      </article>
    `).join("")}
  `;
}

function renderAnalysisCards(analysis) {
  const traditional = analysis.traditional || {};
  const lstm = analysis.lstm_signal || {};
  const asset = analysis.asset || {};
  const insights = analysis.market_insights || {};
  const health = analysis.symbol_health || {};
  const mtf = analysis.multi_timeframe || {};
  const regime = analysis.market_regime || {};
  const payoutFilter = analysis.payout_filter || {};
  const candlePattern = analysis.candlestick_pattern_detail || {};
  const supportResistance = analysis.support_resistance || {};
  const breakout = analysis.breakout_structure || {};
  const quad = analysis.quad_analysis || {};
  const quadSections = quad.sections || {};
  const voting = analysis.ai_voting || {};
  const indicatorSnapshot = quad.indicator_snapshot || {};
  const nearestSupport = supportResistance.nearest_support;
  const nearestResistance = supportResistance.nearest_resistance;
  const modelWeights = Object.entries(analysis.model_weights || {})
    .map(([name, value]) => `${name}: ${Number(value).toFixed(2)}`)
    .join(" | ") || "uniform";

  els.detailMethod.textContent = analysis.degraded
    ? `degraded | ${analysis.analysis_method || "unknown"}`
    : (analysis.analysis_method || "unknown");

  els.analysisCards.innerHTML = `
    <article class="analysis-card">
      <span>AI Voting</span>
      <strong>${voting.label || "Wait"}</strong>
      <p>${voting.trade_ready ? "Execution ready" : "Not execution-ready"} | Confidence ${formatConfidenceWithDirection(analysis.confidence, analysis.direction)}</p>
    </article>
    <article class="analysis-card">
      <span>Quad Trend</span>
      <strong>${quadSections.trend?.status || "blocked"}</strong>
      <p>${quadSections.trend?.summary || "No trend summary yet."}</p>
    </article>
    <article class="analysis-card">
      <span>Quad S/R</span>
      <strong>${quadSections.support_resistance?.status || "blocked"}</strong>
      <p>${quadSections.support_resistance?.summary || "No S/R summary yet."}</p>
    </article>
    <article class="analysis-card">
      <span>Quad Momentum</span>
      <strong>${quadSections.momentum_volatility?.status || "blocked"}</strong>
      <p>${quadSections.momentum_volatility?.summary || "No momentum summary yet."}</p>
    </article>
    <article class="analysis-card">
      <span>Quad Price Action</span>
      <strong>${quadSections.price_action?.status || "blocked"}</strong>
      <p>${quadSections.price_action?.summary || "No price action summary yet."}</p>
    </article>
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
    <article class="analysis-card">
      <span>Symbol Health</span>
      <strong>${health.score ?? "--"}/100</strong>
      <p>Speed ${health.update_speed ?? "--"} | Stability ${health.data_stability ?? "--"}</p>
    </article>
    <article class="analysis-card">
      <span>Multi-Timeframe</span>
      <strong>${mtf.label || "N/A"}</strong>
      <p>${mtf.current_timeframe || analysis.timeframe || "--"} -> ${mtf.higher_timeframe || "--"} | ${formatConfidenceWithDirection(mtf.confidence, mtf.direction)}</p>
    </article>
    <article class="analysis-card">
      <span>Market Regime</span>
      <strong>${regime.regime || "unknown"}</strong>
      <p>Score ${regime.score ?? "--"} | Efficiency ${regime.efficiency ?? "--"}</p>
    </article>
    <article class="analysis-card">
      <span>Price Action</span>
      <strong>${candlePattern.name || "none"}</strong>
      <p>${candlePattern.bias || "neutral"} | Strength ${candlePattern.strength ?? "--"}</p>
    </article>
    <article class="analysis-card">
      <span>Breakout State</span>
      <strong>${breakout.state || "none"}</strong>
      <p>PA Score ${analysis.price_action_score ?? 0}</p>
    </article>
    <article class="analysis-card full">
      <span>Technical Summary</span>
      <strong>${analysis.candle_pattern || "N/A"}</strong>
      <p>${analysis.technical_summary || "No technical summary available."}</p>
    </article>
    <article class="analysis-card full">
      <span>Indicator Snapshot</span>
      <strong>${indicatorSnapshot.source || "manual"}</strong>
      <p>EMA200 ${formatPrice(indicatorSnapshot.ema_200)} | RSI ${indicatorSnapshot.rsi == null ? "--" : Number(indicatorSnapshot.rsi).toFixed(1)} | ATR ${indicatorSnapshot.atr == null ? "--" : Number(indicatorSnapshot.atr).toFixed(5)} | STOCH ${indicatorSnapshot.stochastic_k == null ? "--" : Number(indicatorSnapshot.stochastic_k).toFixed(1)}</p>
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
    <article class="analysis-card full">
      <span>Confirmation Summary</span>
      <strong>${mtf.status || "unavailable"}</strong>
      <p>${mtf.summary || "Higher timeframe confirmation is not available yet."}</p>
    </article>
    <article class="analysis-card full">
      <span>Payout Filter</span>
      <strong>${payoutFilter.passed ? "passed" : "blocked"}</strong>
      <p>${payoutFilter.summary || "Payout filter status unavailable."}</p>
    </article>
    <article class="analysis-card full">
      <span>Price Action Summary</span>
      <strong>${candlePattern.name || "none"}</strong>
      <p>${candlePattern.summary || "No candlestick pattern summary is available yet."}</p>
    </article>
    <article class="analysis-card full">
      <span>Support / Resistance</span>
      <strong>${nearestSupport ? `S ${formatPrice(nearestSupport.level)}` : "S --"} | ${nearestResistance ? `R ${formatPrice(nearestResistance.level)}` : "R --"}</strong>
      <p>${nearestSupport ? `${nearestSupport.touches} support touches` : "No support"} | ${nearestResistance ? `${nearestResistance.touches} resistance touches` : "No resistance"}</p>
    </article>
    <article class="analysis-card full">
      <span>Breakout Summary</span>
      <strong>${breakout.state || "none"}</strong>
      <p>${breakout.summary || "No breakout or retest structure is active."}</p>
    </article>
    <article class="analysis-card full">
      <span>Quad Summary</span>
      <strong>${quad.label || "Wait"}</strong>
      <p>${quad.summary || "Quad-analysis summary unavailable."}</p>
    </article>
  `;
}

function renderTradeJournal(items) {
  if (!items || items.length === 0) {
    els.tradeJournal.innerHTML = '<div class="empty-card">Closed trades will appear here after the first completed result.</div>';
    return;
  }

  els.tradeJournal.innerHTML = items.map((item) => `
    <article class="trade-entry">
      <div class="trade-top">
        <div>
          <strong>${item.pair || "Unknown pair"}</strong>
          <div class="trade-meta">
            <span>${(item.direction || "neutral").toUpperCase()}</span>
            <span>${item.timeframe || "--"}</span>
            <span>${item.result || "pending"}</span>
          </div>
        </div>
        <span class="result-pill ${item.result === "win" ? "win" : item.result === "loss" ? "loss" : "neutral"}">${item.profit == null ? "--" : `$${Number(item.profit).toFixed(2)}`}</span>
      </div>
      <p>${item.reason || item.result_source || "No reason captured yet."}</p>
    </article>
  `).join("");
}

function renderJournalAnalytics(data) {
  const summary = data?.summary || {};
  const bestPair = data?.best_pair;
  const worstPair = data?.worst_pair;
  const bestTf = data?.best_timeframe;
  const streak = data?.recent_streak || {};
  const marketSplit = (data?.market_split || [])
    .map((item) => `${item.key}: ${Math.round(item.win_rate || 0)}% (${item.trades})`)
    .join(" | ");

  if (!summary.total_trades) {
    els.journalAnalytics.innerHTML = '<div class="empty-card">Journal analytics will appear after enough closed trades are recorded.</div>';
    return;
  }

  els.journalAnalytics.innerHTML = `
    <article class="analysis-card">
      <span>Total Trades</span>
      <strong>${summary.total_trades ?? 0}</strong>
      <p>Win rate ${formatPercent(summary.win_rate)}</p>
    </article>
    <article class="analysis-card">
      <span>Net Profit</span>
      <strong>$${Number(summary.net_profit || 0).toFixed(2)}</strong>
      <p>Expectancy $${Number(summary.expectancy || 0).toFixed(2)}</p>
    </article>
    <article class="analysis-card">
      <span>Best Pair</span>
      <strong>${bestPair?.key || "N/A"}</strong>
      <p>${bestPair ? `${formatPercent(bestPair.win_rate)} | $${Number(bestPair.profit || 0).toFixed(2)}` : "No pair edge yet"}</p>
    </article>
    <article class="analysis-card">
      <span>Weakest Pair</span>
      <strong>${worstPair?.key || "N/A"}</strong>
      <p>${worstPair ? `${formatPercent(worstPair.win_rate)} | $${Number(worstPair.profit || 0).toFixed(2)}` : "No weak pair yet"}</p>
    </article>
    <article class="analysis-card">
      <span>Best Timeframe</span>
      <strong>${bestTf?.key || "N/A"}</strong>
      <p>${bestTf ? `${formatPercent(bestTf.win_rate)} | ${bestTf.trades} trades` : "No timeframe edge yet"}</p>
    </article>
    <article class="analysis-card">
      <span>Recent Streak</span>
      <strong>${streak.type || "flat"}</strong>
      <p>${streak.count || 0} trades | Avg confidence ${formatPercent(summary.avg_confidence)}</p>
    </article>
    <article class="analysis-card full">
      <span>Market Split</span>
      <strong>${marketSplit || "N/A"}</strong>
      <p>Tracks whether OTC or regular markets are performing better in your recent history.</p>
    </article>
  `;

  setText(els.topMetricWinRate, formatPercent(summary.win_rate));
  setText(els.topMetricTrades, String(summary.total_trades ?? 0));
  setText(els.topMetricProfit, `$${Number(summary.net_profit || 0).toFixed(2)}`);
}

function renderCurrencyHeatmap(items) {
  return;
}

function initChart() {
  if (state.chart) {
    state.chart.remove();
  }
  state.chartPriceLines = [];

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

function clearChartPriceLines() {
  if (!state.candleSeries || !state.chartPriceLines.length) {
    state.chartPriceLines = [];
    return;
  }

  state.chartPriceLines.forEach((line) => {
    try {
      if (typeof state.candleSeries.removePriceLine === "function") {
        state.candleSeries.removePriceLine(line);
      }
    } catch (error) {
      console.error("Failed to remove chart price line:", error);
    }
  });
  state.chartPriceLines = [];
}

function renderSupportResistanceLines(supportResistance) {
  clearChartPriceLines();

  if (!state.candleSeries || typeof state.candleSeries.createPriceLine !== "function") {
    return;
  }

  const nearestSupport = supportResistance?.nearest_support;
  const nearestResistance = supportResistance?.nearest_resistance;
  const lines = [];

  if (nearestSupport?.level != null) {
    lines.push({
      price: Number(nearestSupport.level),
      color: "rgba(18, 209, 137, 0.85)",
      lineWidth: 2,
      lineStyle: 2,
      axisLabelVisible: true,
      title: `Support x${nearestSupport.touches ?? "-"}`,
    });
  }

  if (nearestResistance?.level != null) {
    lines.push({
      price: Number(nearestResistance.level),
      color: "rgba(255, 103, 120, 0.85)",
      lineWidth: 2,
      lineStyle: 2,
      axisLabelVisible: true,
      title: `Resistance x${nearestResistance.touches ?? "-"}`,
    });
  }

  lines.forEach((options) => {
    try {
      const line = state.candleSeries.createPriceLine(options);
      if (line) {
        state.chartPriceLines.push(line);
      }
    } catch (error) {
      console.error("Failed to create chart price line:", error);
    }
  });
}

function setChartCandles(candles) {
  if (!state.candleSeries) {
    initChart();
  }

  if (!state.candleSeries) {
    return;
  }

  if (!candles || candles.length === 0) {
    clearChartPriceLines();
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
  const nextFeedKey = assetId ? `${assetId}:${timeframe}` : null;
  if (state.liveFeedKey === nextFeedKey && (state.livePollTimer || state.liveSocket)) {
    return;
  }
  state.liveFeedKey = nextFeedKey;

  stopLiveFeed();

  if (!assetId) {
    state.liveFeedKey = null;
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${protocol}://${window.location.host}/ws/live-feed?asset_id=${encodeURIComponent(assetId)}&timeframe=${encodeURIComponent(timeframe)}`;
  let socket = null;

  const applyLivePayload = (payload) => {
    if (assetId !== state.selectedAssetId) {
      return;
    }
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
    state.livePollTimer = window.setInterval(pollOnce, 3200);
  };

  if (PREFER_HTTP_LIVE_FEED) {
    startHttpPolling();
    return;
  }

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
    setText(els.summaryMarketCount, "0");
    return;
  }

  els.marketBoard.innerHTML = items.map((item) => `
    <button class="market-row ${item.id === state.selectedAssetId ? "active" : ""}" data-asset-id="${item.id}">
      <div class="market-main">
        <div class="market-top">
          <strong class="market-name">${item.display_name}</strong>
          <span class="tag">${item.market_type.toUpperCase()}</span>
        </div>
        <div class="market-stats">
          <span>Payout ${item.payout == null ? "N/A" : formatPercent(item.payout)}</span>
          <span>Health ${item.health?.score ?? "--"}</span>
          <span>${item.symbol || item.quotex_symbol || "--"}</span>
        </div>
      </div>
      <span class="health-pill ${formatHealthClass(item.health?.score ?? 0)}">${item.health?.grade || "watch"}</span>
    </button>
  `).join("");

  setText(els.summaryMarketCount, String(items.length));

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
    setText(els.summaryScannerStatus, "No setups");
    return;
  }

  els.topSetups.innerHTML = items.map((item, index) => `
    <article class="signal-row" data-asset-id="${item.asset.id}">
      <div class="signal-main">
        <div class="signal-top">
          <strong class="signal-pair">#${index + 1} ${item.asset.display_name}</strong>
          <span class="direction-pill ${formatPillClass(item.direction)}">${recommendationDirectionLabel(item.direction)}</span>
        </div>
        <div class="signal-stats">
          <span>Confidence ${formatConfidenceWithDirection(item.confidence, item.direction)}</span>
          <span>Payout ${formatPercent(item.asset.payout)}</span>
          <span>PA ${item.price_action_score ?? 0}</span>
          <span>${item.breakout_structure?.state || "no breakout"}</span>
        </div>
      </div>
      <div class="signal-cta">
        <span class="mini-note">${item.asset.market_type.toUpperCase()}</span>
        <button class="inline-button ${item.direction === "put" ? "put" : ""}">${item.direction === "put" ? "PUT" : "CALL"}</button>
      </div>
    </article>
  `).join("");

  setText(els.summaryScannerStatus, `${items.length} ranked`);

  els.topSetups.querySelectorAll("[data-asset-id]").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedAssetId = card.dataset.assetId;
      renderMarkets(state.filteredMarkets);
      loadAnalysis();
    });
  });
}

async function loadHealth() {
  if (state.tradeSubmitting) {
    return;
  }
  const data = await safeFetchJson("/api/health", { timeoutMs: 10000 });
  els.connectionBadge.textContent = data.connection || "Unknown";
  els.connectionBadge.classList.remove("loading");
  els.balanceBadge.textContent = `Balance: ${formatBalance(data.balance)}`;
  if (els.connectionBadge) {
    els.connectionBadge.classList.toggle("loading", !String(data.connection || "").trim());
  }
}

async function loadMarkets() {
  if (state.tradeSubmitting) {
    return;
  }
  const requestId = ++state.marketsRequestId;
  const data = await safeFetchJson(`/api/markets?category=${encodeURIComponent(state.category)}`, { timeoutMs: 12000 });
  if (requestId !== state.marketsRequestId) {
    return;
  }
  state.markets = data.items || [];
  filterMarkets();

  const selectedStillVisible = state.filteredMarkets.some((item) => item.id === state.selectedAssetId);
  if (!selectedStillVisible) {
    state.selectedAssetId = state.filteredMarkets.length > 0 ? state.filteredMarkets[0].id : null;
  }

  renderMarkets(state.filteredMarkets);
  const selected = state.filteredMarkets.find((item) => item.id === state.selectedAssetId);
  updateSummarySelectedAsset(selected?.display_name || "--");
}

async function loadScanner() {
  if (state.tradeSubmitting) {
    return;
  }
  const requestId = ++state.scannerRequestId;
  els.topSetups.innerHTML = '<div class="loading-state">Scanning the live Quotex board...</div>';
  try {
    const data = await safeFetchJson(`/api/top-setups?timeframe=${encodeURIComponent(state.timeframe)}&category=${encodeURIComponent(state.category)}&limit=3`, { timeoutMs: 18000 });
    if (requestId !== state.scannerRequestId) {
      return;
    }
    const ranked = [...(data.items || [])].sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
    renderTopSetups(ranked);

    const bullishCount = (data.items || []).filter((item) => item.direction === "call").length;
    const total = Math.max(1, (data.items || []).length);
    const marketValue = Math.round((bullishCount / total) * 100);
    els.sentimentValue.textContent = `${marketValue}%`;
    els.sentimentLabel.textContent = sentimentText(marketValue);
    els.sentimentMeter.style.width = `${marketValue}%`;
    els.updatedAt.textContent = new Date().toLocaleTimeString();
    pushSystemFeed(`Scanner ranked ${ranked.length} setup(s) on ${state.timeframe}.`, ranked.length ? "green" : "amber");
  } catch (error) {
    if (requestId !== state.scannerRequestId) {
      return;
    }
    els.topSetups.innerHTML = `<div class="empty-card">${error.message}</div>`;
    els.sentimentValue.textContent = "--%";
    els.sentimentLabel.textContent = "Scanner unavailable";
    els.sentimentMeter.style.width = "0%";
    setText(els.summaryScannerStatus, "Scanner error");
    pushSystemFeed(`Scanner failed: ${error.message}`, "red");
  }
}

async function loadAnalysis(options = {}) {
  const { silent = false } = options;
  if (state.tradeSubmitting && silent) {
    return;
  }
  const requestId = ++state.analysisRequestId;
  if (!state.selectedAssetId) {
    state.lastAnalysis = null;
    state.liveFeedKey = null;
    stopAnalysisPolling();
    updateSummarySelectedAsset("--");
    setText(els.topMetricConfidence, "--");
    els.analysisCards.innerHTML = '<div class="empty-card">Choose a pair from the market board to open the analysis.</div>';
    renderLiveAnalysis(null);
    renderReasons([]);
    setChartCandles([]);
    clearChartPriceLines();
    setTradeButtonsEnabled(false);
    els.tradeStatus.textContent = "Choose a pair to start the live recommendation.";
    return;
  }

  if (!silent) {
    els.analysisCards.innerHTML = '<div class="loading-state">Running layered analysis...</div>';
    els.liveAnalysisFlow.innerHTML = `
      <article class="pipeline-card warning">
        <div class="pipeline-mark">...</div>
        <div>
          <div class="pipeline-head">
            <strong>Running quad-analysis</strong>
            <span class="direction-pill neutral">Live Analysis</span>
          </div>
          <p>Checking trend, support/resistance, momentum, and candle confirmation for the selected pair.</p>
        </div>
      </article>
    `;
  }
  try {
    const data = await safeFetchJson(`/api/analyze?asset_id=${encodeURIComponent(state.selectedAssetId)}&timeframe=${encodeURIComponent(state.timeframe)}`, { timeoutMs: 18000 });
    if (requestId !== state.analysisRequestId) {
      return;
    }
    state.lastAnalysis = data;
    updateHero(data);
    renderAnalysisCards(data);
    renderLiveAnalysis(data);
    renderReasons(data.decision_reasons || []);
    setChartCandles(data.price_series || []);
    renderSupportResistanceLines(data.support_resistance || {});
    connectLiveFeed(state.selectedAssetId, state.timeframe);
    startAnalysisPolling();
    els.updatedAt.textContent = new Date().toLocaleTimeString();

    if (typeof data.live_sentiment === "number") {
      els.sentimentValue.textContent = `${Math.round(data.live_sentiment)}%`;
      els.sentimentLabel.textContent = sentimentText(data.live_sentiment);
      els.sentimentMeter.style.width = `${Math.max(0, Math.min(100, data.live_sentiment))}%`;
    }

    const payoutPassed = data.payout_filter?.passed !== false;
    const canTrade = ["call", "put"].includes(data.direction) && (Number(data.confidence || 0) > 0) && payoutPassed;
    setTradeButtonsEnabled(canTrade);
    if (canTrade && data.ai_voting?.trade_ready) {
      els.tradeStatus.textContent = `Strong setup ready: ${directionLabel(data.direction)} on ${data.asset.display_name} with confidence ${formatConfidenceWithDirection(data.confidence, data.direction)}.`;
    } else if (canTrade) {
      els.tradeStatus.textContent = data.ai_voting?.summary || `Setup loaded for ${data.asset.display_name}, but it remains in watch mode.`;
    } else {
      els.tradeStatus.textContent = data.payout_filter?.summary || data.degraded_reason || "Direct execution is disabled until a live CALL or PUT setup is available.";
    }
    if (!silent) {
      pushSystemFeed(`Analyzed ${data.asset.display_name} on ${state.timeframe}.`, canTrade ? "green" : "blue");
    }
  } catch (error) {
    if (requestId !== state.analysisRequestId) {
      return;
    }
    state.lastAnalysis = null;
    setTradeButtonsEnabled(false);
    stopAnalysisPolling();
    if (!silent) {
      renderLiveAnalysis(null);
      renderReasons([]);
      setChartCandles([]);
      clearChartPriceLines();
      els.detailMethod.textContent = "analysis failed";
      els.analysisCards.innerHTML = `<div class="empty-card">${error.message}</div>`;
      els.tradeStatus.textContent = `Analysis failed: ${error.message}`;
      pushSystemFeed(`Analysis failed: ${error.message}`, "red");
    }
  }
}

function triggerBackgroundLoads(options = {}) {
  const {
    includeScanner = true,
    includeJournal = false,
    includeHeatmap = false,
  } = options;

  const tasks = [];
  if (includeScanner) tasks.push(loadScanner());
  if (includeJournal) {
    tasks.push(loadTradeJournal());
    tasks.push(loadJournalAnalytics());
  }
  Promise.allSettled(tasks).catch((error) => {
    console.error("Background panel refresh failed:", error);
  });
}

async function loadTradeJournal() {
  if (state.tradeSubmitting) {
    return;
  }
  try {
    const data = await safeFetchJson("/api/trade-journal?limit=20", { timeoutMs: 10000 });
    renderTradeJournal(data.items || []);
  } catch (error) {
    els.tradeJournal.innerHTML = `<div class="empty-card">${error.message}</div>`;
  }
}

async function loadJournalAnalytics() {
  if (state.tradeSubmitting) {
    return;
  }
  try {
    const data = await safeFetchJson("/api/journal-analytics", { timeoutMs: 10000 });
    renderJournalAnalytics(data);
  } catch (error) {
    els.journalAnalytics.innerHTML = `<div class="empty-card">${error.message}</div>`;
  }
}

async function loadCurrencyHeatmap() {
  return;
}

async function refreshAll() {
  const healthResult = await Promise.allSettled([loadHealth(), loadMarkets()]);
  const failedCore = healthResult.find((result) => result.status === "rejected");
  if (failedCore) {
    const error = failedCore.reason;
    console.error(error);
    els.marketBoard.innerHTML = `<div class="empty-card">${error.message}</div>`;
    els.tradeStatus.textContent = error.message;
    pushSystemFeed(`Refresh failed: ${error.message}`, "red");
    return;
  }

  await loadAnalysis();
  triggerBackgroundLoads({ includeScanner: true, includeJournal: true, includeHeatmap: false });
  pushSystemFeed("Dashboard refreshed.", "blue");
}

async function executeTrade(direction) {
  if (!state.lastAnalysis || state.tradeSubmitting) {
    return;
  }

  const userId = getConfiguredUserId();
  if (!userId || userId <= 0) {
    els.tradeStatus.textContent = "Set a valid User ID first.";
    renderUserIdState();
    return;
  }
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 55000);
  state.tradeSubmitting = true;
  stopAnalysisPolling();
  stopLiveFeed();
  setTradeButtonsEnabled(["call", "put"].includes(state.lastAnalysis.direction) && Number(state.lastAnalysis.confidence || 0) > 0);
  els.tradeStatus.textContent = `Submitting ${direction.toUpperCase()} trade...`;
  pushSystemFeed(`Submitting ${direction.toUpperCase()} on ${state.lastAnalysis.asset.display_name}.`, "amber");

  try {
    const headers = { "Content-Type": "application/json" };
    const apiToken = getApiToken();
    if (apiToken) {
      headers["X-API-Key"] = apiToken;
    }

    const response = await fetch("/api/execute", {
      method: "POST",
      headers,
      signal: controller.signal,
      body: JSON.stringify({
        asset_id: state.lastAnalysis.asset.id,
        timeframe: state.timeframe,
        direction,
        user_id: userId,
        confidence: state.lastAnalysis.confidence,
      }),
    });

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : { detail: await response.text() };
    if (!response.ok) {
      throw new Error(payload.detail || "Trade execution failed");
    }

    els.tradeStatus.textContent = `Trade opened: ${payload.pair} ${payload.direction.toUpperCase()} | $${payload.amount} | ID ${payload.trade_id}`;
    pushSystemFeed(`Trade opened: ${payload.pair} ${payload.direction.toUpperCase()} | $${payload.amount}.`, "green");
    window.setTimeout(() => triggerBackgroundLoads({ includeScanner: true, includeJournal: true, includeHeatmap: false }), 10000);
  } catch (error) {
    els.tradeStatus.textContent = error.name === "AbortError"
      ? "Trade request timed out. Please try again."
      : error.message;
    pushSystemFeed(els.tradeStatus.textContent, "red");
  } finally {
    clearTimeout(timeoutId);
    state.tradeSubmitting = false;
    const canTrade = !!state.lastAnalysis
      && ["call", "put"].includes(state.lastAnalysis.direction)
      && Number(state.lastAnalysis.confidence || 0) > 0
      && state.lastAnalysis.payout_filter?.passed !== false;
    setTradeButtonsEnabled(canTrade);
    window.setTimeout(() => {
      if (state.selectedAssetId) {
        connectLiveFeed(state.selectedAssetId, state.timeframe);
        startAnalysisPolling();
      }
    }, 3500);
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
  const selected = state.filteredMarkets.find((item) => item.id === state.selectedAssetId);
  updateSummarySelectedAsset(selected?.display_name || "--");
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
  stopAnalysisPolling();
  await loadAnalysis();
  triggerBackgroundLoads({ includeScanner: true, includeJournal: false, includeHeatmap: false });
});

els.categorySelect.addEventListener("change", async (event) => {
  state.category = event.target.value;
  state.selectedAssetId = null;
  stopAnalysisPolling();
  await loadMarkets();
  await loadAnalysis();
  triggerBackgroundLoads({ includeScanner: true, includeJournal: false, includeHeatmap: false });
});

els.pairSearchInput.addEventListener("input", handlePairSearch);
els.refreshButton.addEventListener("click", refreshAll);
els.saveApiTokenButton.addEventListener("click", () => {
  const value = String(els.apiTokenInput.value || "").trim();
  if (!value) {
    els.apiTokenStatus.textContent = "Enter a valid API token.";
    return;
  }
  window.localStorage.setItem(API_TOKEN_STORAGE_KEY, value);
  renderApiTokenState();
  els.tradeStatus.textContent = "API token saved for this browser.";
  pushSystemFeed("API token saved locally in this browser.", "blue");
});
els.saveUserIdButton.addEventListener("click", () => {
  const value = Number(els.userIdInput.value || 0);
  if (!value || value <= 0) {
    els.userIdStatus.textContent = "Enter a valid numeric User ID.";
    return;
  }
  window.localStorage.setItem(USER_ID_STORAGE_KEY, String(value));
  renderUserIdState();
  els.tradeStatus.textContent = `User ID ${value} saved for execution.`;
  pushSystemFeed(`User ID ${value} saved for execution.`, "blue");
});
els.scanButton.addEventListener("click", loadScanner);
els.tradeCallButton.addEventListener("click", () => executeTrade("call"));
els.tradePutButton.addEventListener("click", () => executeTrade("put"));

initTelegramTheme();
renderApiTokenState();
renderUserIdState();
setTradeButtonsEnabled(false);
renderSystemFeed();
updateClock();
window.setInterval(updateClock, 1000);
setText(els.topMetricWinRate, "--");
setText(els.topMetricTrades, "--");
setText(els.topMetricProfit, "$0.00");
setText(els.topMetricConfidence, "--");
setText(els.summaryMarketCount, "--");
updateSummarySelectedAsset("--");
setText(els.summaryScannerStatus, "Idle");

try {
  initChart();
} catch (error) {
  reportUiError(`Initial chart boot failed: ${error.message || error}`);
}

refreshAll().catch((error) => {
  reportUiError(`Startup failed: ${error.message || error}`);
});
