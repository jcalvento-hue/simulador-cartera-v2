"""
Cálculo de indicadores técnicos server-side.
Se usan al momento de registrar una operación para guardar el snapshot
del estado técnico del instrumento en ese instante.
"""
import math


def _ema(precios: list, periodo: int) -> list:
    """EMA con lista de precios (float). Devuelve lista de floats, None para warmup."""
    if not precios:
        return []
    k = 2 / (periodo + 1)
    ema = [precios[0]]
    for i in range(1, len(precios)):
        ema.append(precios[i] * k + ema[-1] * (1 - k))
    return [None if i < periodo - 1 else round(v, 4) for i, v in enumerate(ema)]


def _rsi(precios: list, n: int = 14) -> list:
    """RSI con suavizado de Wilder. Devuelve lista, None para warmup."""
    result = [None] * len(precios)
    if len(precios) < n + 1:
        return result
    avg_gain, avg_loss = 0.0, 0.0
    for i in range(1, n + 1):
        d = precios[i] - precios[i - 1]
        if d > 0:
            avg_gain += d
        else:
            avg_loss += abs(d)
    avg_gain /= n
    avg_loss /= n
    result[n] = 100.0 if avg_loss == 0 else round(100 - 100 / (1 + avg_gain / avg_loss), 2)
    for i in range(n + 1, len(precios)):
        d = precios[i] - precios[i - 1]
        g = d if d > 0 else 0.0
        l = abs(d) if d < 0 else 0.0
        avg_gain = (avg_gain * (n - 1) + g) / n
        avg_loss = (avg_loss * (n - 1) + l) / n
        result[i] = 100.0 if avg_loss == 0 else round(100 - 100 / (1 + avg_gain / avg_loss), 2)
    return result


def _bb(precios: list, n: int = 20):
    """Bollinger Bands. Devuelve (upper, mid, lower) listas."""
    upper, mid, lower = [], [], []
    for i in range(len(precios)):
        if i < n - 1:
            upper.append(None); mid.append(None); lower.append(None)
            continue
        sl = precios[i - n + 1: i + 1]
        mean = sum(sl) / n
        std = math.sqrt(sum((x - mean) ** 2 for x in sl) / n)
        mid.append(round(mean, 4))
        upper.append(round(mean + 2 * std, 4))
        lower.append(round(mean - 2 * std, 4))
    return upper, mid, lower


def _macd(precios: list):
    """MACD (12,26,9). Devuelve (macd_line, signal, histo) del último punto disponible."""
    ema12 = _ema(precios, 12)
    ema26 = _ema(precios, 26)
    macd_line = [
        round(e12 - e26, 4) if (e12 is not None and e26 is not None) else None
        for e12, e26 in zip(ema12, ema26)
    ]
    # Signal: EMA 9 sobre los valores no-None del macd_line
    filled = [v for v in macd_line if v is not None]
    signal_filled = _ema(filled, 9)
    # Reconstruir con Nones para alinear índices
    signal: list = []
    filled_idx = 0
    for v in macd_line:
        if v is None:
            signal.append(None)
        else:
            signal.append(signal_filled[filled_idx] if filled_idx < len(signal_filled) else None)
            filled_idx += 1
    histo = [
        round(m - s, 4) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, signal)
    ]
    return macd_line, signal, histo


def snapshot(precios: list) -> dict:
    """
    Calcula todos los indicadores sobre la lista de precios y devuelve
    el valor más reciente de cada uno (último elemento no-None).

    Retorna un dict con:
      - ema10, ema20, ema50: float o None
      - rsi14: float o None  (con interpretación textual)
      - bb_upper, bb_mid, bb_lower: float o None
      - macd_line, macd_signal, macd_histo: float o None
      - precio_actual: float
      - n_puntos: int (cantidad de precios usados)
    """
    if not precios:
        return {}

    def last(lst):
        """Último valor no-None de una lista."""
        for v in reversed(lst):
            if v is not None:
                return v
        return None

    precio_actual = precios[-1]

    ema10_lst  = _ema(precios, 10)
    ema20_lst  = _ema(precios, 20)
    ema50_lst  = _ema(precios, 50)
    rsi_lst    = _rsi(precios, 14)
    bb_u, bb_m, bb_l = _bb(precios, 20)
    macd_l, macd_s, macd_h = _macd(precios)

    ema10  = last(ema10_lst)
    ema20  = last(ema20_lst)
    ema50  = last(ema50_lst)
    rsi14  = last(rsi_lst)
    bb_upper = last(bb_u)
    bb_mid   = last(bb_m)
    bb_lower = last(bb_l)
    macd_line   = last(macd_l)
    macd_signal = last(macd_s)
    macd_histo  = last(macd_h)

    # Señales interpretadas (texto corto para el docente)
    seniales = {}
    if rsi14 is not None:
        if rsi14 >= 70:
            seniales["rsi"] = f"RSI {rsi14:.1f} — sobrecompra"
        elif rsi14 <= 30:
            seniales["rsi"] = f"RSI {rsi14:.1f} — sobreventa"
        else:
            seniales["rsi"] = f"RSI {rsi14:.1f} — neutral"

    if ema10 and ema20:
        if precio_actual > ema20:
            seniales["ema20"] = f"Precio ({precio_actual:.2f}) > EMA20 ({ema20:.2f}) — tendencia alcista"
        else:
            seniales["ema20"] = f"Precio ({precio_actual:.2f}) < EMA20 ({ema20:.2f}) — tendencia bajista"

    if ema20 and ema50:
        if ema20 > ema50:
            seniales["cruce_ema"] = f"EMA20 ({ema20:.2f}) > EMA50 ({ema50:.2f}) — golden cross activo"
        else:
            seniales["cruce_ema"] = f"EMA20 ({ema20:.2f}) < EMA50 ({ema50:.2f}) — death cross activo"

    if bb_upper and bb_lower and bb_mid:
        if precio_actual > bb_upper:
            seniales["bb"] = f"Precio por encima de banda superior ({bb_upper:.2f}) — posible sobrecompra"
        elif precio_actual < bb_lower:
            seniales["bb"] = f"Precio por debajo de banda inferior ({bb_lower:.2f}) — posible sobreventa"
        else:
            seniales["bb"] = f"Precio dentro de bandas [{bb_lower:.2f} – {bb_upper:.2f}]"

    if macd_histo is not None:
        if macd_histo > 0:
            seniales["macd"] = f"MACD histograma positivo ({macd_histo:.4f}) — momentum alcista"
        else:
            seniales["macd"] = f"MACD histograma negativo ({macd_histo:.4f}) — momentum bajista"

    return {
        "n_puntos": len(precios),
        "precio_actual": round(precio_actual, 4),
        "ema10":  ema10,
        "ema20":  ema20,
        "ema50":  ema50,
        "rsi14":  rsi14,
        "bb_upper": bb_upper,
        "bb_mid":   bb_mid,
        "bb_lower": bb_lower,
        "macd_line":   macd_line,
        "macd_signal": macd_signal,
        "macd_histo":  macd_histo,
        "seniales": seniales,
    }
