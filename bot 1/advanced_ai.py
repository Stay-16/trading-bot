from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger("AdvAI")

# ── Lazy imports for heavy ML libraries ───────────────────
_NP = None
_SKLEARN_ENSEMBLE = None
_SKLEARN_SCALER = None
_JOBLIB = None
_XGB = None
_LSTM = _DENSE = _INPUT = _SEQUENTIAL = _LOAD_MODEL = None


def _np():
    global _NP
    if _NP is None:
        import numpy as _NP
    return _NP


def _sklearn_ensemble():
    global _SKLEARN_ENSEMBLE
    if _SKLEARN_ENSEMBLE is None:
        from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, GradientBoostingClassifier
        _SKLEARN_ENSEMBLE = (RandomForestClassifier, ExtraTreesClassifier, GradientBoostingClassifier)
    return _SKLEARN_ENSEMBLE


def _sklearn_scaler():
    global _SKLEARN_SCALER
    if _SKLEARN_SCALER is None:
        from sklearn.preprocessing import StandardScaler
        _SKLEARN_SCALER = StandardScaler
    return _SKLEARN_SCALER


def _joblib():
    global _JOBLIB
    if _JOBLIB is None:
        import joblib as _JOBLIB
    return _JOBLIB


def _xgb():
    global _XGB
    if _XGB is None:
        try:
            from xgboost import XGBClassifier
            _XGB = XGBClassifier
        except Exception:
            _XGB = None
    return _XGB


def _load_tf():
    global _LSTM, _DENSE, _INPUT, _SEQUENTIAL, _LOAD_MODEL
    if all(x is not None for x in (_LSTM, _DENSE, _INPUT, _SEQUENTIAL, _LOAD_MODEL)):
        return True
    try:
        import importlib
        kl = importlib.import_module("tensorflow.keras.layers")
        km = importlib.import_module("tensorflow.keras.models")
        _LSTM = getattr(kl, "LSTM", None)
        _DENSE = getattr(kl, "Dense", None)
        _INPUT = getattr(kl, "Input", None)
        _SEQUENTIAL = getattr(km, "Sequential", None)
        _LOAD_MODEL = getattr(km, "load_model", None)
        return all(x is not None for x in (_LSTM, _DENSE, _INPUT, _SEQUENTIAL, _LOAD_MODEL))
    except Exception:
        return False


class AdvancedAISystem:
    def __init__(self, model_dir: str = "."):
        self.model_dir = model_dir
        self.models: dict = {}
        self.scaler = _sklearn_scaler()()
        self.training_data: list = []
        self.performance_history: list = []
        self.market_patterns: dict = {}
        self.lstm_model = None
        self.model_weights: dict = {}
        self.sequence_buffers = defaultdict(lambda: deque(maxlen=20))
        self.sequence_length = 20
        self.feature_count = 8
        self._last_features: Optional[np.ndarray] = None

        self.label_to_index = {-2: 0, -1: 1, 0: 2, 1: 3, 2: 4}
        self.index_to_label = {0: -2, 1: -1, 2: 0, 3: 1, 4: 2}

        _load_tf()
        self._load()

    # ── Path helpers ───────────────────────────────────────

    def _path(self, filename: str) -> str:
        return os.path.join(self.model_dir, filename)

    # ── Persistence ────────────────────────────────────────

    def _load(self):
        model_file = self._path("advanced_ai_models.pkl")
        scaler_file = self._path("advanced_ai_scaler.pkl")
        weights_file = self._path("advanced_ai_model_weights.json")
        data_file = self._path("advanced_trading_data.json")
        lstm_file = self._path("advanced_lstm_model.keras")

        try:
            if os.path.exists(model_file):
                loaded = _joblib().load(model_file)
                if isinstance(loaded, dict):
                    self.models = loaded
                    self.model = loaded.get("random_forest") or next(iter(loaded.values()), None)
                else:
                    self.models = {"random_forest": loaded}
                self.scaler = _joblib().load(scaler_file) if os.path.exists(scaler_file) else _sklearn_scaler()()
                log.info("AI models loaded: %s", list(self.models.keys()))
            else:
                self._init_models()
                log.info("New AI models initialized")

            if _load_tf() and _LOAD_MODEL and os.path.exists(lstm_file):
                self.lstm_model = _LOAD_MODEL(lstm_file)
                log.info("LSTM model loaded")

            if os.path.exists(weights_file):
                with open(weights_file) as f:
                    self.model_weights = json.load(f)

            if os.path.exists(data_file):
                with open(data_file) as f:
                    data = json.load(f)
                    self.training_data = data.get("training_data", [])
                    self.performance_history = data.get("performance_history", [])
                    self.market_patterns = data.get("market_patterns", {})
        except Exception as e:
            log.warning("AI load error: %s — reinitializing", e)
            self._init_models()

    def _init_models(self):
        RF, ET, GB = _sklearn_ensemble()
        self.models = {
            "random_forest": RF(n_estimators=200, max_depth=20, random_state=42),
            "extra_trees": ET(n_estimators=200, max_depth=18, random_state=42),
            "gradient_boosting": GB(n_estimators=150, learning_rate=0.05, random_state=42),
        }
        xgb_cls = _xgb()
        if xgb_cls is not None:
            self.models["xgboost"] = xgb_cls(n_estimators=150, max_depth=6, learning_rate=0.05, random_state=42, eval_metric="mlogloss")
        self.model_weights = {name: 1.0 for name in self.models}
        if _load_tf() and _SEQUENTIAL and _LSTM and _DENSE and _INPUT:
            self.lstm_model = _SEQUENTIAL([
                _INPUT(shape=(self.sequence_length, self.feature_count)),
                _LSTM(32, return_sequences=False),
                _DENSE(32, activation="relu"),
                _DENSE(5, activation="softmax"),
            ])
            self.lstm_model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])

    def save(self):
        try:
            joblib.dump(self.models, self._path("advanced_ai_models.pkl"))
            joblib.dump(self.scaler, self._path("advanced_ai_scaler.pkl"))
            if self.lstm_model is not None:
                self.lstm_model.save(self._path("advanced_lstm_model.keras"), overwrite=True)
            with open(self._path("advanced_ai_model_weights.json"), "w") as f:
                json.dump(self.model_weights, f, indent=2)
            with open(self._path("advanced_trading_data.json"), "w") as f:
                json.dump({
                    "training_data": self.training_data[-2000:],
                    "performance_history": self.performance_history,
                    "market_patterns": self.market_patterns,
                }, f, indent=2)
            log.info("AI system saved (%d models, %d samples)", len(self.models), len(self.training_data))
        except Exception as e:
            log.error("AI save error: %s", e)

    # ── Feature extraction (50+ features) ──────────────────

    def extract_advanced_features(self, indicators: dict) -> np.ndarray:
        try:
            features = []
            close = indicators.get("close", 1) or 1
            high = indicators.get("high", close) or close
            low = indicators.get("low", close) or close
            open_price = indicators.get("open", close) or close

            features.extend([
                indicators.get("RSI", 50),
                indicators.get("MACD.macd", 0),
                indicators.get("MACD.signal", 0),
                indicators.get("Stoch.K", 50),
                indicators.get("Stoch.D", 50),
                indicators.get("CCI", 0),
                indicators.get("ADX", 0),
                indicators.get("Williams %R", 0),
                indicators.get("Ultimate Oscillator", 50),
            ])

            ma_keys = ["EMA5", "EMA10", "EMA20", "EMA50", "EMA100", "EMA200", "SMA20", "SMA50"]
            ma_values = [indicators.get(k, close) for k in ma_keys]
            features.extend(ma_values)

            for i in range(len(ma_values) - 1):
                if ma_values[i + 1] != 0:
                    features.append(ma_values[i] / ma_values[i + 1])
                    features.append(ma_values[i] - ma_values[i + 1])

            prev_close = indicators.get("prev_close", close) or close
            features.extend([
                high - low,
                (high - low) / close if close else 0,
                (close - open_price) / close if close else 0,
                (close - prev_close) / prev_close if prev_close else 0,
                (high - close) / (high - low) if high != low else 0.5,
            ])

            volume = indicators.get("volume", 0) or 0
            vol_sma = indicators.get("Volume SMA", volume) or volume
            features.extend([
                volume,
                indicators.get("RSI", 50) - 50,
                indicators.get("MACD.macd", 0) - indicators.get("MACD.signal", 0),
                vol_sma,
                volume / vol_sma if vol_sma else 0,
            ])

            now = datetime.now()
            features.extend([
                now.hour, now.weekday(),
                1 if 8 <= now.hour <= 17 else 0,
                1 if now.weekday() < 5 else 0,
            ])

            total_range = high - low
            body = abs(close - open_price)
            features.extend([
                body / total_range if total_range else 0,
                (high - max(close, open_price)) / total_range if total_range else 0,
                (min(close, open_price) - low) / total_range if total_range else 0,
            ])

            return np.array(features).reshape(1, -1)
        except Exception as e:
            log.debug("Feature extraction error: %s", e)
            return np.array([50] * 50).reshape(1, -1)

    # ── Prediction ─────────────────────────────────────────

    def _available_models(self):
        return {n: m for n, m in self.models.items() if m is not None}

    def _ensemble_probs(self, features_scaled: np.ndarray) -> dict:
        avail = self._available_models()
        if not avail:
            raise RuntimeError("No models available")
        combined = {l: 0.0 for l in [-2, -1, 0, 1, 2]}
        total_w = 0.0
        for name, model in avail.items():
            w = float(self.model_weights.get(name, 1.0))
            total_w += w
            try:
                probs = model.predict_proba(features_scaled)[0]
                classes = getattr(model, "classes_", [])
                for idx, cls in enumerate(classes):
                    label = int(cls)
                    if name == "xgboost" and label in self.index_to_label:
                        label = self.index_to_label[label]
                    combined[int(label)] += float(probs[idx]) * w
            except Exception:
                continue
        n = total_w if total_w > 0 else len(avail)
        return {k: v / n for k, v in combined.items()}

    def predict(self, features: np.ndarray) -> dict:
        self._last_features = features
        if len(self.training_data) < 100:
            return {"direction": "neutral", "confidence": 50, "method": "insufficient_data"}
        try:
            scaled = self.scaler.transform(features)
            probs = self._ensemble_probs(scaled)
            pred = max(probs, key=probs.get)

            if pred in (1, 2):
                direction = "UP"
                confidence = int(probs[pred] * 100)
            elif pred in (-1, -2):
                direction = "DOWN"
                confidence = int(probs[pred] * 100)
            else:
                direction = "WAIT"
                confidence = int(probs[0] * 100)

            return {
                "direction": direction,
                "confidence": min(95, confidence),
                "method": "ensemble_ai",
                "probabilities": probs,
                "models_used": list(self._available_models().keys()),
            }
        except Exception as e:
            log.debug("AI predict error: %s", e)
            return {"direction": "neutral", "confidence": 50, "method": "error"}

    # ── Online learning ────────────────────────────────────

    def learn_from_trade(self, trade_data: dict):
        try:
            if trade_data.get("result") not in ("win", "loss"):
                return
            features = trade_data.get("features")
            if features is None or (isinstance(features, np.ndarray) and features.size == 0):
                features = self._last_features
            if features is None or (isinstance(features, np.ndarray) and features.size == 0):
                return
            if isinstance(features, list):
                features = np.array(features)
            if features.ndim == 1:
                features = features.reshape(1, -1)

            outcome = 0
            if trade_data["result"] == "win":
                profit_ratio = trade_data.get("profit", 0) / trade_data.get("amount", 1) if trade_data.get("amount", 1) else 0
                outcome = 2 if profit_ratio > 0.5 else 1
            else:
                loss_ratio = abs(trade_data.get("profit", 0)) / trade_data.get("amount", 1) if trade_data.get("amount", 1) else 0
                outcome = -2 if loss_ratio > 0.5 else -1

            self.training_data.append({
                "features": features.tolist()[0] if features.size > 0 else [],
                "outcome": outcome,
                "timestamp": time.time(),
                "pair": trade_data.get("pair", "unknown"),
                "result": trade_data["result"],
            })

            self._update_market_patterns(trade_data)
            self.update_performance_metrics(trade_data)
            self.update_market_patterns(trade_data)
            log.info("AI learned from trade: %s (%d samples)", trade_data["result"], len(self.training_data))

            if len(self.training_data) >= 100:
                asyncio.create_task(self.retrain())
            self.save()
        except Exception as e:
            log.debug("learn_from_trade error: %s", e)

    def _update_market_patterns(self, trade_data: dict):
        pair = trade_data.get("pair", "unknown")
        key = f"{pair}_{trade_data.get('timeframe', '')}"
        pat = self.market_patterns.get(key, {"total": 0, "wins": 0})
        pat["total"] += 1
        if trade_data.get("result") == "win":
            pat["wins"] += 1
        pat["win_rate"] = pat["wins"] / pat["total"]
        pat["last_updated"] = time.time()
        self.market_patterns[key] = pat

    async def retrain(self):
        if len(self.training_data) < 100:
            return
        try:
            X = np.array([ex["features"] for ex in self.training_data])
            y = np.array([ex["outcome"] for ex in self.training_data])
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
            for name, model in self._available_models().items():
                model.fit(X_scaled, y)
            log.info("AI models retrained on %d samples", len(X))

            if self.lstm_model and len(self.training_data) >= self.sequence_length:
                try:
                    seq_X, seq_y = self._build_lstm_sequences()
                    self.lstm_model.fit(seq_X, seq_y, epochs=3, verbose=0, batch_size=16)
                    log.info("LSTM retrained")
                except Exception as e:
                    log.debug("LSTM retrain error: %s", e)
            self.save()
        except Exception as e:
            log.error("AI retrain error: %s", e)

    def _build_lstm_sequences(self):
        features = []
        labels = []
        for i in range(len(self.training_data) - self.sequence_length):
            seq = self.training_data[i:i + self.sequence_length]
            features.append([ex["features"] for ex in seq])
            labels.append(self.training_data[i + self.sequence_length]["outcome"])
        return np.array(features, dtype=np.float32), np.array(labels)

    def update_sequence_buffer(self, pair: str, price_vector: list):
        key = f"{pair}_1m"
        self.sequence_buffers[key].append(price_vector)
        return list(self.sequence_buffers[key])

    # ── Market context adjustments ──────────────────────────

    def adjust_confidence_by_market(self, confidence: int, market_context: dict) -> int:
        adjusted = confidence
        volatility = market_context.get('volatility', 0)
        if volatility > 0.03:
            adjusted -= 10
        elif volatility < 0.01:
            adjusted += 5
        current_hour = datetime.now().hour
        if 8 <= current_hour <= 17:
            adjusted += 5
        else:
            adjusted -= 5
        return max(10, min(95, adjusted))

    def combine_confidence(self, trad_confidence: int, ai_confidence: int) -> int:
        ai_weight = min(0.8, len(self.training_data) / 500)
        trad_weight = 1 - ai_weight
        combined = (trad_confidence * trad_weight) + (ai_confidence * ai_weight)
        return min(95, int(combined))

    # ── Enhanced prediction ─────────────────────────────────

    async def ai_enhanced_prediction(self, features: np.ndarray, traditional_signal: dict,
                                      market_context: dict, pair: str = "", timeframe: str = "",
                                      indicators: dict = None) -> dict:
        try:
            if len(self.training_data) < 100:
                return {
                    'direction': traditional_signal['direction'],
                    'confidence': traditional_signal['confidence'],
                    'method': 'traditional_fallback',
                    'ai_confidence': 50,
                    'risk_level': 'medium',
                    'models_used': list(self._available_models().keys()) or ['random_forest'],
                }
            scaled = self.scaler.transform(features)
            probs = self._ensemble_probs(scaled)
            pred = max(probs, key=probs.get)

            if pred in (1, 2):
                direction = "UP"
                ai_confidence = int(probs[pred] * 100)
                risk_level = "low" if pred == 2 else "medium"
            elif pred in (-1, -2):
                direction = "DOWN"
                ai_confidence = int(probs[pred] * 100)
                risk_level = "low" if pred == -2 else "medium"
            else:
                direction = "WAIT"
                ai_confidence = int(probs[0] * 100)
                risk_level = "high"

            adjusted_confidence = self.adjust_confidence_by_market(ai_confidence, market_context)
            final_confidence = self.combine_confidence(traditional_signal['confidence'], adjusted_confidence)

            return {
                'direction': direction,
                'confidence': final_confidence,
                'method': 'ensemble_ai',
                'ai_confidence': ai_confidence,
                'risk_level': risk_level,
                'probabilities': probs,
                'market_adjustment': adjusted_confidence - ai_confidence,
                'models_used': list(self._available_models().keys()),
            }
        except Exception as e:
            log.debug("AI enhanced prediction error: %s", e)
            return {
                'direction': traditional_signal['direction'],
                'confidence': traditional_signal['confidence'],
                'method': 'fallback',
                'ai_confidence': 50,
                'risk_level': 'high',
                'models_used': list(self._available_models().keys()) or ['random_forest'],
            }

    # ── Performance tracking ────────────────────────────────

    def update_performance_metrics(self, trade_data: dict):
        try:
            performance_record = {
                'timestamp': time.time(),
                'result': trade_data.get('result', 'unknown'),
                'confidence': trade_data.get('confidence', 50),
                'profit': trade_data.get('profit', 0),
                'pair': trade_data.get('pair', 'unknown'),
                'direction': trade_data.get('direction', 'unknown'),
                'timeframe': trade_data.get('timeframe', 'unknown'),
                'risk_level': trade_data.get('risk_level', 'medium'),
            }
            self.performance_history.append(performance_record)
            if len(self.performance_history) > 2000:
                self.performance_history = self.performance_history[-2000:]
        except Exception as e:
            log.debug("update_performance_metrics error: %s", e)

    def update_market_patterns(self, trade_data: dict):
        try:
            pair = trade_data['pair']
            timeframe = trade_data.get('timeframe', '')
            result = trade_data['result']
            key = f"{pair}_{timeframe}"
            if key not in self.market_patterns:
                self.market_patterns[key] = {
                    'total_trades': 0,
                    'wins': 0,
                    'win_rate': 0,
                    'last_updated': time.time(),
                }
            pattern = self.market_patterns[key]
            pattern['total_trades'] += 1
            if result == 'win':
                pattern['wins'] += 1
            pattern['win_rate'] = pattern['wins'] / pattern['total_trades']
            pattern['last_updated'] = time.time()
        except Exception as e:
            log.debug("update_market_patterns error: %s", e)

    def get_performance_stats(self) -> dict:
        if not self.performance_history:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'avg_confidence': 0,
                'recent_trades': 0,
                'profit_factor': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'expectancy': 0,
            }
        try:
            wins = len([t for t in self.performance_history if t.get('result') == 'win'])
            total = len(self.performance_history)
            win_rate = wins / total if total > 0 else 0
            confidences = [t.get('confidence', 0) for t in self.performance_history if t.get('confidence') is not None]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            recent = self.performance_history[-10:]
            recent_wins = len([t for t in recent if t.get('result') == 'win'])
            total_profit = sum([t.get('profit', 0) for t in self.performance_history if t.get('profit', 0) > 0])
            total_loss = abs(sum([t.get('profit', 0) for t in self.performance_history if t.get('profit', 0) < 0]))
            profit_factor = total_profit / total_loss if total_loss > 0 else 0
            win_trades = [t for t in self.performance_history if t.get('result') == 'win']
            loss_trades = [t for t in self.performance_history if t.get('result') == 'loss']
            avg_win = sum([t.get('profit', 0) for t in win_trades]) / len(win_trades) if win_trades else 0
            avg_loss = sum([abs(t.get('profit', 0)) for t in loss_trades]) / len(loss_trades) if loss_trades else 0
            if win_trades and loss_trades:
                expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
            else:
                expectancy = 0
            return {
                'total_trades': total,
                'win_rate': round(win_rate * 100, 2),
                'avg_confidence': round(avg_confidence, 2),
                'recent_trades': recent_wins,
                'profit_factor': round(profit_factor, 2),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'expectancy': round(expectancy, 2),
            }
        except Exception as e:
            log.debug("get_performance_stats error: %s", e)
            return {
                'total_trades': 0,
                'win_rate': 0,
                'avg_confidence': 0,
                'recent_trades': 0,
                'profit_factor': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'expectancy': 0,
            }

    def get_market_insights(self, pair: str, timeframe: str) -> dict:
        key = f"{pair}_{timeframe}"
        pattern = self.market_patterns.get(key, {})
        win_rate = pattern.get('win_rate', 0)
        if win_rate > 0.6:
            confidence = 'high'
        elif win_rate > 0.5:
            confidence = 'medium'
        else:
            confidence = 'low'
        return {
            'win_rate': win_rate,
            'total_trades': pattern.get('total_trades', 0),
            'last_updated': pattern.get('last_updated', 0),
            'confidence': confidence,
        }

    # ── Retraining with validation split ────────────────────

    async def retrain_model(self):
        if len(self.training_data) < 100:
            return
        try:
            X = np.array([ex["features"] for ex in self.training_data])
            y = np.array([ex["outcome"] for ex in self.training_data])
            split_index = max(1, int(len(X) * 0.8))
            X_train, X_val = X[:split_index], X[split_index:]
            y_train, y_val = y[:split_index], y[split_index:]
            self.scaler.fit(X_train)
            X_train_scaled = self.scaler.transform(X_train)
            X_val_scaled = self.scaler.transform(X_val) if len(X_val) > 0 else X_train_scaled
            updated_weights = {}
            for model_name, model in self._available_models().items():
                if model_name == 'xgboost':
                    y_train_fit = np.array([self.label_to_index[int(label)] for label in y_train])
                    y_val_eval = np.array([self.label_to_index[int(label)] for label in y_val]) if len(y_val) > 0 else y_train_fit
                    model.fit(X_train_scaled, y_train_fit)
                    score = float(model.score(X_val_scaled, y_val_eval)) if len(X_val_scaled) > 0 else 0.5
                else:
                    model.fit(X_train_scaled, y_train)
                    score = float(model.score(X_val_scaled, y_val)) if len(y_val) > 0 else 0.5
                updated_weights[model_name] = max(0.05, score)
                log.info("Retrained %s on %d samples with validation score %.3f", model_name, len(X), score)
            total_weight = sum(updated_weights.values()) or 1.0
            self.model_weights = {
                model_name: round(weight / total_weight, 4)
                for model_name, weight in updated_weights.items()
            }
            await self.retrain_lstm_model()
            log.info("Models retrained with dynamic weights on %d samples", len(X))
        except Exception as e:
            log.error("retrain_model error: %s", e)

    async def retrain_lstm_model(self):
        try:
            if self.lstm_model is None:
                return
            sequence_examples = []
            sequence_labels = []
            for example in self.training_data:
                sequence = example.get('price_sequence', [])
                if len(sequence) >= self.sequence_length:
                    sequence_examples.append(sequence[-self.sequence_length:])
                    sequence_labels.append(self.label_to_index[int(example['outcome'])])
            if len(sequence_examples) < 30:
                return
            X_seq = np.array(sequence_examples, dtype=np.float32)
            y_seq = np.array(sequence_labels, dtype=np.int32)
            self.lstm_model.fit(X_seq, y_seq, epochs=5, batch_size=16, verbose=0)
            log.info("Retrained LSTM on %d sequences", len(X_seq))
        except Exception as e:
            log.debug("retrain_lstm_model error: %s", e)
