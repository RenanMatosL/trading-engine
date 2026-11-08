class SimpleCandleSession:
    def __init__(self, preset: SimpleCandlePreset):
        self._preset = preset
        self._signal: dict | None = None  # {bar_time, is_buy, high, low, mid, sl, tp}
        self._last_bar_time = None

    def on_bar_closed(self, bar, zscore, now):
        if zscore < self._preset.detector.std_ref:
            return None
        
        # Lógica do v2.20: cor do candle define a direção
        is_buy = bar.close > bar.open
        mid = (bar.high + bar.low) / 2.0
        sl_dist = self._preset.sl_points * 1.0  # 1 ponto = 1.0
        tp_dist = self._preset.tp_points * 1.0
        
        if is_buy:
            sl = bar.low - sl_dist
            tp = mid + tp_dist
        else:
            sl = bar.high + sl_dist
            tp = mid - tp_dist
        
        self._signal = {
            "bar_time": bar.time,
            "is_buy": is_buy,
            "high": bar.high,
            "low": bar.low,
            "mid": mid,
            "sl": sl,
            "tp": tp,
        }
        return self._signal

    def on_tick(self, snapshot):
        if self._signal is None:
            return None
        
        # Entrada no meio do candle (pullback)
        mid = self._signal["mid"]
        is_buy = self._signal["is_buy"]
        
        if is_buy and snapshot.ask <= mid:
            intent = self._make_intent(snapshot)
            self._signal = None  # consome o sinal
            return intent
        elif not is_buy and snapshot.bid >= mid:
            intent = self._make_intent(snapshot)
            self._signal = None
            return intent
        return None