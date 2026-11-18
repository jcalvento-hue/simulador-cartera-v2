"""
Descarga de historial real de precios para los instrumentos del simulador.

Fuente: stooq.com (CSV público, sin auth, funciona desde servidores)
  - Acciones argentinas: ticker.ba (ej: ggal.ba)
  - CEDEARs/NYSE:        ticker.us (ej: aapl.us)
  - Bonos/FCI:           sin fuente → GBM fallback

Retorna lista de dicts: [{"fecha": date, "precio": float}, ...]
ordenada de más antiguo a más reciente.
"""

import httpx
import csv
import io
from datetime import date, datetime, timedelta
from typing import List, Dict

AÑOS_HISTORIAL = 3
TIMEOUT = 20

# Mapeo ticker simulador → ticker stooq.com
_STOOQ_MAP: Dict[str, str] = {
    # Acciones Merval (BCBA)
    "GGAL":  "ggal.ba",
    "YPF":   "ypfd.ba",
    "BMA":   "bma.ba",
    "PAMP":  "pamp.ba",
    "TXAR":  "txar.ba",
    "ALUA":  "alua.ba",
    "SUPV":  "supv.ba",
    "CEPU":  "cepu.ba",
    "LOMA":  "loma.ba",
    "BBAR":  "bbar.ba",
    "TECO2": "teco2.ba",
    "CRES":  "cres.ba",
    # CEDEARs (NYSE/NASDAQ)
    "AAPL":  "aapl.us",
    "GOOGL": "googl.us",
    "AMZN":  "amzn.us",
    "MSFT":  "msft.us",
    "TSLA":  "tsla.us",
    "BRKB":  "brk-b.us",
}

# Sin fuente desde servidor → GBM fallback
_SIN_FUENTE = {"AL30", "GD30", "AL35", "AE38", "TX26", "T2X5",
               "FCICONV", "FCIMOD", "FCIAGR"}


def _descargar_stooq(ticker_stooq: str) -> List[Dict]:
    """
    Descarga CSV de stooq.com para el ticker dado.
    URL: https://stooq.com/q/d/l/?s={ticker}&i=d
    CSV: Date,Open,High,Low,Close,Volume
    """
    try:
        fecha_fin = date.today()
        fecha_ini = fecha_fin - timedelta(days=365 * AÑOS_HISTORIAL)
        url = (
            f"https://stooq.com/q/d/l/"
            f"?s={ticker_stooq}"
            f"&d1={fecha_ini.strftime('%Y%m%d')}"
            f"&d2={fecha_fin.strftime('%Y%m%d')}"
            f"&i=d"
        )
        print(f"[historial_real] stooq GET {url}", flush=True)

        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            r = client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            })
            r.raise_for_status()
            content = r.text

        print(f"[historial_real] stooq {ticker_stooq}: respuesta {len(content)} bytes, primeras líneas: {content[:200]}", flush=True)

        # stooq devuelve "No data" cuando el ticker no existe
        if "No data" in content or len(content.strip()) < 30:
            print(f"[historial_real] stooq {ticker_stooq}: sin datos", flush=True)
            return []

        result = []
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            try:
                fecha_str = row.get("Date", "")
                close_str = row.get("Close", "")
                if not fecha_str or not close_str:
                    continue
                d = datetime.strptime(fecha_str.strip(), "%Y-%m-%d").date()
                close = float(close_str.strip())
                if close > 0:
                    result.append({"fecha": d, "precio": round(close, 2)})
            except (ValueError, KeyError):
                continue

        result = sorted(result, key=lambda x: x["fecha"])
        print(f"[historial_real] stooq {ticker_stooq}: {len(result)} puntos OK", flush=True)
        return result

    except Exception as e:
        import traceback
        print(f"[historial_real] stooq ERROR {ticker_stooq}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        return []


def obtener_historial_real(ticker: str) -> List[Dict]:
    """
    Punto de entrada único. Retorna [] si falla (caller usa GBM fallback).
    """
    print(f"[historial_real] obtener_historial_real({ticker})", flush=True)

    if ticker in _SIN_FUENTE:
        print(f"[historial_real] {ticker}: sin fuente → GBM fallback", flush=True)
        return []

    if ticker in _STOOQ_MAP:
        datos = _descargar_stooq(_STOOQ_MAP[ticker])
        if datos:
            print(f"[historial_real] {ticker}: OK stooq, {len(datos)} puntos", flush=True)
            return datos
        print(f"[historial_real] {ticker}: stooq vacío → GBM fallback", flush=True)
        return []

    print(f"[historial_real] {ticker}: ticker desconocido → GBM fallback", flush=True)
    return []
