"""
Descarga del precio actual de cada instrumento usando Finnhub API.
Plan gratuito: 60 req/min — suficiente para los 18 tickers con cotización.

Tickers sin cotización en Finnhub (bonos AR, FCIs) → GBM fallback.

Retorna dict: {ticker: precio_float} para los que tienen datos,
o {} si falla todo.
"""

import httpx
from typing import Dict

FINNHUB_API_KEY = "dbuu3hpr01qrflsmqu20dbuu3hpr01qrflsmqu2g"
TIMEOUT = 10

# Mapeo ticker simulador → símbolo Finnhub
# Acciones argentinas: exchange BCBA, formato "BCBA:GGAL"
# CEDEARs/NYSE: símbolo directo
_FINNHUB_MAP: Dict[str, str] = {
    # Acciones Merval (BCBA)
    "GGAL":  "BCBA:GGAL",
    "YPF":   "BCBA:YPFD",
    "BMA":   "BCBA:BMA",
    "PAMP":  "BCBA:PAMP",
    "TXAR":  "BCBA:TXAR",
    "ALUA":  "BCBA:ALUA",
    "SUPV":  "BCBA:SUPV",
    "CEPU":  "BCBA:CEPU",
    "LOMA":  "BCBA:LOMA",
    "BBAR":  "BCBA:BBAR",
    "TECO2": "BCBA:TECO2",
    "CRES":  "BCBA:CRES",
    # CEDEARs / NYSE
    "AAPL":  "AAPL",
    "GOOGL": "GOOGL",
    "AMZN":  "AMZN",
    "MSFT":  "MSFT",
    "TSLA":  "TSLA",
    "BRKB":  "BRK.B",
}

# Sin cotización en Finnhub → GBM fallback
_SIN_FUENTE = {"AL30", "GD30", "AL35", "AE38", "TX26", "T2X5",
               "FCICONV", "FCIMOD", "FCIAGR"}


def _quote_finnhub(simbolo: str) -> float | None:
    """Consulta el precio actual de un símbolo en Finnhub. Retorna None si falla."""
    url = f"https://finnhub.io/api/v1/quote?symbol={simbolo}&token={FINNHUB_API_KEY}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
        # Finnhub retorna: c=current, h=high, l=low, o=open, pc=prev close
        precio = data.get("c") or data.get("pc")
        if precio and precio > 0:
            return round(float(precio), 2)
        return None
    except Exception as e:
        print(f"[historial_real] finnhub ERROR {simbolo}: {e}", flush=True)
        return None


def obtener_precios_actuales() -> Dict[str, float]:
    """
    Descarga el precio actual de todos los tickers con cotización en Finnhub.
    Retorna {ticker: precio} para los que tienen datos.
    Los tickers sin cotización (bonos, FCIs) no se incluyen → GBM fallback.
    """
    precios = {}
    for ticker, simbolo in _FINNHUB_MAP.items():
        precio = _quote_finnhub(simbolo)
        if precio:
            precios[ticker] = precio
            print(f"[historial_real] {ticker} ({simbolo}): {precio}", flush=True)
        else:
            print(f"[historial_real] {ticker} ({simbolo}): sin precio → GBM fallback", flush=True)
    print(f"[historial_real] Total: {len(precios)}/{len(_FINNHUB_MAP)} precios obtenidos", flush=True)
    return precios


# Mantener compatibilidad con código legacy que llama obtener_historial_real()
# (ya no se usa desde market.py, pero por si acaso)
def obtener_historial_real(ticker: str):
    return []
