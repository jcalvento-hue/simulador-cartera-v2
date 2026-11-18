"""
Descarga del precio actual de cada instrumento usando:
- Rava Bursátil (scraping og:description) para acciones argentinas (BCBA)
- Finnhub API para acciones NYSE/US — plan gratuito 60 req/min

Tickers sin cotización (bonos AR, FCIs) → GBM fallback.
Retorna dict: {ticker: precio_float}
"""

import re
import httpx
from typing import Dict

FINNHUB_API_KEY = "dbuu3hpr01qrflsmqu20dbuu3hpr01qrflsmqu2g"
TIMEOUT = 15

# Acciones argentinas → ticker en Rava (URL: rava.com/perfil/{ticker})
_RAVA_MAP: Dict[str, str] = {
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

# Headers para evitar bloqueo por user-agent
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9",
}


def _quote_rava(simbolo: str) -> float | None:
    """
    Scraping del precio actual desde rava.com/perfil/{simbolo}.
    El precio está en el meta og:description: '$4.705 (-3,14%). ...'
    Formato argentino: punto=miles, coma=decimal → convertir a float.
    """
    url = f"https://www.rava.com/perfil/{simbolo}"
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            html = r.text

        # Buscar og:description: content="$4.705 (-3,14%). ..."
        m = re.search(r'og:description["\s]+content="?\$([0-9.,]+)', html)
        if not m:
            # Fallback: buscar en p2-price div: <div class="p2-price">4.705,00</div>
            m = re.search(r'class="p2-price">([0-9.,]+)<', html)
        if not m:
            print(f"[historial_real] rava: no se encontró precio para {simbolo}", flush=True)
            return None

        precio_str = m.group(1)
        # Formato AR: "4.705,00" → quitar puntos de miles, reemplazar coma decimal por punto
        precio_str = precio_str.replace(".", "").replace(",", ".")
        precio = float(precio_str)
        if precio > 0:
            return round(precio, 2)
        return None

    except Exception as e:
        print(f"[historial_real] rava ERROR {simbolo}: {e}", flush=True)
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
    - Acciones AR (BCBA): scraping Rava Bursátil (og:description)
    - Acciones US (NYSE): Finnhub API
    - Bonos y FCIs: no se incluyen → GBM fallback
    Retorna {ticker: precio_float}
    """
    precios = {}

    # Acciones argentinas — Rava scraping
    for ticker, simbolo in _RAVA_MAP.items():
        precio = _quote_rava(simbolo)
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

    total = len(_RAVA_MAP) + len(_FINNHUB_MAP)
    print(f"[historial_real] Total: {len(precios)}/{total} precios obtenidos", flush=True)
    return precios


# Compatibilidad con código legacy
def obtener_historial_real(ticker: str):
    return []
