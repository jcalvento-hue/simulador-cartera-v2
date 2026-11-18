"""
Descarga del precio actual de cada instrumento usando:
- Twelve Data API para acciones argentinas (BCBA) — plan gratuito 800 req/día
- Finnhub API para acciones NYSE/US — plan gratuito 60 req/min

Tickers sin cotización (bonos AR, FCIs) → GBM fallback.
Retorna dict: {ticker: precio_float}
"""

import httpx
from typing import Dict

TWELVEDATA_API_KEY = "852f053f299440ba9ed639a6aa30514e"
FINNHUB_API_KEY    = "dbuu3hpr01qrflsmqu20dbuu3hpr01qrflsmqu2g"
TIMEOUT = 10

# Acciones argentinas → Twelve Data (BCBA)
_TWELVEDATA_MAP: Dict[str, str] = {
    "GGAL":  "GGAL",
    "YPF":   "YPFD",
    "BMA":   "BMA",
    "PAMP":  "PAMP",
    "TXAR":  "TXAR",
    "ALUA":  "ALUA",
    "SUPV":  "SUPV",
    "CEPU":  "CEPU",
    "LOMA":  "LOMA",
    "BBAR":  "BBAR",
    "TECO2": "TECO2",
    "CRES":  "CRES",
}

# Acciones NYSE → Finnhub
_FINNHUB_MAP: Dict[str, str] = {
    "AAPL":  "AAPL",
    "GOOGL": "GOOGL",
    "AMZN":  "AMZN",
    "MSFT":  "MSFT",
    "TSLA":  "TSLA",
    "BRKB":  "BRK.B",
}


def _quote_twelvedata(simbolo: str) -> float | None:
    """Consulta precio actual en Twelve Data (exchange BCBA)."""
    url = (
        f"https://api.twelvedata.com/price"
        f"?symbol={simbolo}&exchange=BCBA&apikey={TWELVEDATA_API_KEY}"
    )
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
        # Twelve Data retorna {"price": "1234.56"} o {"code": 400, "message": "..."}
        if "price" in data:
            precio = float(data["price"])
            if precio > 0:
                return round(precio, 2)
        print(f"[historial_real] twelvedata respuesta inesperada {simbolo}: {data}", flush=True)
        return None
    except Exception as e:
        print(f"[historial_real] twelvedata ERROR {simbolo}: {e}", flush=True)
        return None


def _quote_finnhub(simbolo: str) -> float | None:
    """Consulta precio actual en Finnhub (NYSE/US)."""
    url = f"https://finnhub.io/api/v1/quote?symbol={simbolo}&token={FINNHUB_API_KEY}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
        precio = data.get("c") or data.get("pc")
        if precio and precio > 0:
            return round(float(precio), 2)
        return None
    except Exception as e:
        print(f"[historial_real] finnhub ERROR {simbolo}: {e}", flush=True)
        return None


def obtener_precios_actuales() -> Dict[str, float]:
    """
    Descarga precios actuales para todos los tickers con cotización.
    - Acciones AR (BCBA): Twelve Data
    - Acciones US (NYSE): Finnhub
    - Bonos y FCIs: no se incluyen → GBM fallback
    Retorna {ticker: precio_float}
    """
    precios = {}

    # Acciones argentinas — Twelve Data
    for ticker, simbolo in _TWELVEDATA_MAP.items():
        precio = _quote_twelvedata(simbolo)
        if precio:
            precios[ticker] = precio
            print(f"[historial_real] {ticker} (BCBA:{simbolo}): {precio}", flush=True)
        else:
            print(f"[historial_real] {ticker} (BCBA:{simbolo}): sin precio → GBM fallback", flush=True)

    # Acciones US — Finnhub
    for ticker, simbolo in _FINNHUB_MAP.items():
        precio = _quote_finnhub(simbolo)
        if precio:
            precios[ticker] = precio
            print(f"[historial_real] {ticker} ({simbolo}): {precio}", flush=True)
        else:
            print(f"[historial_real] {ticker} ({simbolo}): sin precio → GBM fallback", flush=True)

    total = len(_TWELVEDATA_MAP) + len(_FINNHUB_MAP)
    print(f"[historial_real] Total: {len(precios)}/{total} precios obtenidos", flush=True)
    return precios


# Compatibilidad con código legacy
def obtener_historial_real(ticker: str):
    return []
