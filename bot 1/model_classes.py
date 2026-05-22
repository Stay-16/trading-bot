from __future__ import annotations

import logging

log = logging.getLogger("ModelClasses")

_NP = None
_SKLEARN_ENSEMBLE = None
_SKLEARN_SCALER = None
_JOBLIB = None
_XGB = None

def _np():
    global _NP
    if _NP is None:
        import numpy as _NP
    return _NP

def get_sklearn_ensemble():
    global _SKLEARN_ENSEMBLE
    if _SKLEARN_ENSEMBLE is None:
        from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier, RandomForestClassifier
        _SKLEARN_ENSEMBLE = (ExtraTreesClassifier, GradientBoostingClassifier, RandomForestClassifier)
    return _SKLEARN_ENSEMBLE

def get_scaler():
    global _SKLEARN_SCALER
    if _SKLEARN_SCALER is None:
        from sklearn.preprocessing import StandardScaler
        _SKLEARN_SCALER = StandardScaler
    return _SKLEARN_SCALER

def get_joblib():
    global _JOBLIB
    if _JOBLIB is None:
        import joblib as _JOBLIB
    return _JOBLIB

def get_xgb():
    global _XGB
    if _XGB is None:
        try:
            from xgboost import XGBClassifier
            _XGB = XGBClassifier
        except Exception:
            _XGB = None
    return _XGB

def load_tf():
    try:
        import importlib
        kl = importlib.import_module("tensorflow.keras.layers")
        km = importlib.import_module("tensorflow.keras.models")
        return (
            getattr(kl, "LSTM", None),
            getattr(kl, "Dense", None),
            getattr(kl, "Input", None),
            getattr(km, "Sequential", None),
            getattr(km, "load_model", None),
        )
    except Exception:
        return None, None, None, None, None
