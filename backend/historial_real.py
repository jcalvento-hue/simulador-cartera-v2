"""
Descarga de historial real de precios para los instrumentos del simulador.

Fuentes:
  - yfinance   → acciones argentinas (GGAL.BA, etc.) y CEDEARs (AAPL, etc.)
  - Ambito     → bonos soberanos (AL30, GD30, etc.)
  - CAFCI      → FCI (cuotapartes diarias de fondos reales mapeados)

Retorna siempre una lista de dicts: [{"fecha": date, "precio": float}, ...]
ordenada de más antiguo a más reciente, con ~3 años de historia.
El último elemento es el precio más reciente → se usa como precio inicial
de la simulación.
"""

import httpx
import logging
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ─── Configuración ────────────────────────────────────────────────────────────

AÑOS_HISTORIAL = 3
TIMEOUT = 15  # segundos por request

# Mapeo ticker simulador → ticker yfinance
_YFINANCE_MAP: Dict[str, str] = {
    # Acciones Merval (sufijo .BA = BCBA)
    "GGAL":  "GGAL.BA",
    "YPF":   "YPF.BA",
    "BMA":   "BMA.BA",
    "PAMP":  "PAMP.BA",
    "TXAR":  "TXAR.BA",
    "ALUA":  "ALUA.BA",
    "SUPV":  "SUPV.BA",
    "CEPU":  "CEPU.BA",
    "LOMA":  "LOMA.BA",
    "BBAR":  "BBAR.BA",
    "TECO2": "TECO2.BA",
    "CRES":  "CRES.BA",
    # CEDEARs (cotización en USD en NYSE/NASDAQ)
    "AAPL":  "AAPL",
    "GOOGL": "GOOGL",
    "AMZN":  "AMZN",
    "MSFT":  "MSFT",
    "TSLA":  "TSLA",
    "BRKB":  "BRK-B",
}

# Mapeo ticker simulador → ticker Ambito
_AMBITO_MAP: Dict[str, str] = {
    "AL30": "AL30",
    "GD30": "GD30",
    "AL35": "AL35",
    "AE38": "AE38",
    "TX26": "TX26",
    "T2X5": "T2X5",
}

# Mapeo ticker simulador → ID de fondo en CAFCI
# IDs verificados: Fima Premium MM (conservador), Fima RF (moderado), Fima RV (agresivo)
_CAFCI_MAP: Dict[str, int] = {
    "FCICONV": 1,    # Fima Premium Money Market (Galicia)
    "FCIMOD":  7,    # Fima Renta Fija (Galicia)
    "FCIAGR":  3,    # Fima Renta Variable (Galicia)
}


# ─── yfinance ─────────────────────────────────────────────────────────────────

def _descargar_yfinance(ticker_yf: str) -> List[Dict]:
    """Descarga hasta 3 años de cotizaciones diarias vía yfinance."""
    try:
        import yfinance as yf
        fecha_fin = date.today()
        fecha_ini = fecha_fin - timedelta(days=365 * AÑOS_HISTORIAL)
        df = yf.download(
            ticker_yf,
            start=fecha_ini.isoformat(),
            end=fecha_fin.isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            logger.warning(f"[historial_real] yfinance devolvió vacío para {ticker_yf}")
            return []
        result = []
        for idx, row in df.iterrows():
            d = idx.date() if hasattr(idx, "date") else idx
            close = row["Close"]
            if hasattr(close, "item"):
                close = close.item()
            if close and close > 0:
                result.append({"fecha": d, "precio": round(float(close), 2)})
        return sorted(result, key=lambda x: x["fecha"])
    except Exception as e:
        logger.error(f"[historial_real] yfinance error para {ticker_yf}: {e}")
        return []


# ─── Ambito (bonos) ───────────────────────────────────────────────────────────

def _descargar_ambito(ticker: str) -> List[Dict]:
    """
    Descarga historial de bonos desde Ambito Financiero.
    Endpoint: https://mercados.ambito.com/bonos/{TICKER}/historico-general/{DESDE}/{HASTA}
    Responde JSON: {"fecha": "DD/MM/YYYY", "ultimo": "1234,56", ...}  (lista)
    """
    try:
        fecha_fin = date.today()
        fecha_ini = fecha_fin - timedelta(days=365 * AÑOS_HISTORIAL)
        url = (
            f"https://mercados.ambito.com/bonos/{ticker}/historico-general/"
            f"{fecha_ini.strftime('%d-%m-%Y')}/{fecha_fin.strftime('%d-%m-%Y')}"
        )
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "SimuladorCartera/2.0"})
            r.raise_for_status()
            data = r.json()

        if not isinstance(data, list):
            # Algunos endpoints devuelven {"data": [...]}
            data = data.get("data", []) if isinstance(data, dict) else []

        result = []
        for item in data:
            fecha_str = item.get("fecha", "")
            precio_str = item.get("ultimo", item.get("cierre", ""))
            if not fecha_str or not precio_str:
                continue
            try:
                # Ambito usa DD/MM/YYYY
                d = datetime.strptime(fecha_str.strip(), "%d/%m/%Y").date()
                # Precio puede ser "1.234,56" (separador de miles = punto, decimal = coma)
                precio_limpio = precio_str.replace(".", "").replace(",", ".")
                precio = float(precio_limpio)
                if precio > 0:
                    result.append({"fecha": d, "precio": round(precio, 2)})
            except (ValueError, AttributeError):
                continue

        return sorted(result, key=lambda x: x["fecha"])
    except Exception as e:
        logger.error(f"[historial_real] Ambito error para {ticker}: {e}")
        return []


# ─── CAFCI (FCI) ──────────────────────────────────────────────────────────────

def _descargar_cafci(fondo_id: int) -> List[Dict]:
    """
    Descarga cuotapartes históricas de CAFCI.
    Endpoint: https://api.cafci.org.ar/rendimiento?fondo_id={id}&limit=1000
    Responde JSON lista: [{"fecha": "YYYY-MM-DD", "valor": "1234.5678"}, ...]
    """
    try:
        fecha_fin = date.today()
        fecha_ini = fecha_fin - timedelta(days=365 * AÑOS_HISTORIAL)
        url = (
            f"https://api.cafci.org.ar/rendimiento"
            f"?fondo_id={fondo_id}"
            f"&fechaDesde={fecha_ini.isoformat()}"
            f"&fechaHasta={fecha_fin.isoformat()}"
            f"&limit=2000"
        )
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "SimuladorCartera/2.0"})
            r.raise_for_status()
            data = r.json()

        # CAFCI puede devolver {"data": [...]} o directamente [...]
        rows = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []

        result = []
        for item in rows:
            fecha_str = item.get("fecha", "")
            valor_str = item.get("vcp", item.get("valor", item.get("cuotaparte", "")))
            if not fecha_str or not valor_str:
                continue
            try:
                d = datetime.strptime(fecha_str[:10], "%Y-%m-%d").date()
                valor = float(str(valor_str).replace(",", "."))
                if valor > 0:
                    result.append({"fecha": d, "precio": round(valor, 4)})
            except (ValueError, AttributeError):
                continue

        return sorted(result, key=lambda x: x["fecha"])
    except Exception as e:
        logger.error(f"[historial_real] CAFCI error para fondo_id={fondo_id}: {e}")
        return []


# ─── Función principal ────────────────────────────────────────────────────────

def obtener_historial_real(ticker: str) -> List[Dict]:
    """
    Punto de entrada único. Devuelve historial de ~3 años para el ticker dado.
    Retorna [] si falla (el caller puede usar GBM como fallback).

    Formato: [{"fecha": date, "precio": float}, ...] ordenado de viejo a nuevo.
    """
    if ticker in _YFINANCE_MAP:
        datos = _descargar_yfinance(_YFINANCE_MAP[ticker])
        if datos:
            logger.info(f"[historial_real] {ticker}: {len(datos)} puntos vía yfinance")
            return datos
        logger.warning(f"[historial_real] {ticker}: yfinance falló, se usará GBM")
        return []

    if ticker in _AMBITO_MAP:
        datos = _descargar_ambito(_AMBITO_MAP[ticker])
        if datos:
            logger.info(f"[historial_real] {ticker}: {len(datos)} puntos vía Ambito")
            return datos
        logger.warning(f"[historial_real] {ticker}: Ambito falló, se usará GBM")
        return []

    if ticker in _CAFCI_MAP:
        datos = _descargar_cafci(_CAFCI_MAP[ticker])
        if datos:
            logger.info(f"[historial_real] {ticker}: {len(datos)} puntos vía CAFCI")
            return datos
        logger.warning(f"[historial_real] {ticker}: CAFCI falló, se usará GBM")
        return []

    logger.warning(f"[historial_real] {ticker}: sin fuente conocida, se usará GBM")
    return []
