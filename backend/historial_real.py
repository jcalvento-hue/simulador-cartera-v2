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
from datetime import date, datetime, timedelta
from typing import List, Dict

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
        print(f"[historial_real] yfinance descargando {ticker_yf} desde {fecha_ini} hasta {fecha_fin}", flush=True)

        df = yf.download(
            ticker_yf,
            start=fecha_ini.isoformat(),
            end=fecha_fin.isoformat(),
            auto_adjust=True,
            progress=False,
        )

        print(f"[historial_real] yfinance {ticker_yf}: shape={df.shape}, columns={list(df.columns)}", flush=True)

        if df.empty:
            print(f"[historial_real] yfinance devolvió DataFrame vacío para {ticker_yf}", flush=True)
            return []

        # Manejar MultiIndex de columnas (pandas >= 2.0 con yfinance)
        # En versiones nuevas, df.columns puede ser MultiIndex: ("Close", "GGAL.BA")
        close_col = None
        if hasattr(df.columns, 'levels'):
            # MultiIndex: buscar columna Close
            for col in df.columns:
                if isinstance(col, tuple) and col[0] == "Close":
                    close_col = col
                    break
            if close_col is None:
                # Intentar aplanar
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                close_col = "Close" if "Close" in df.columns else None
        else:
            close_col = "Close" if "Close" in df.columns else None

        if close_col is None:
            print(f"[historial_real] No se encontró columna Close para {ticker_yf}. Columnas: {list(df.columns)}", flush=True)
            return []

        result = []
        for idx, row in df.iterrows():
            d = idx.date() if hasattr(idx, "date") else idx
            close = row[close_col]
            # Extraer escalar de posible Series/array
            if hasattr(close, 'iloc'):
                close = close.iloc[0]
            if hasattr(close, "item"):
                close = close.item()
            try:
                close = float(close)
            except (TypeError, ValueError):
                continue
            if close and close > 0:
                result.append({"fecha": d, "precio": round(close, 2)})

        print(f"[historial_real] yfinance {ticker_yf}: {len(result)} puntos procesados", flush=True)
        return sorted(result, key=lambda x: x["fecha"])

    except Exception as e:
        import traceback
        print(f"[historial_real] yfinance ERROR para {ticker_yf}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        return []


# ─── Ambito (bonos) ───────────────────────────────────────────────────────────

def _descargar_ambito(ticker: str) -> List[Dict]:
    """
    Descarga historial de bonos desde Ambito Financiero.
    Endpoint: https://mercados.ambito.com/bonos/{TICKER}/historico-general/{DESDE}/{HASTA}
    """
    try:
        fecha_fin = date.today()
        fecha_ini = fecha_fin - timedelta(days=365 * AÑOS_HISTORIAL)
        url = (
            f"https://mercados.ambito.com/bonos/{ticker}/historico-general/"
            f"{fecha_ini.strftime('%d-%m-%Y')}/{fecha_fin.strftime('%d-%m-%Y')}"
        )
        print(f"[historial_real] Ambito GET {url}", flush=True)
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "SimuladorCartera/2.0"})
            r.raise_for_status()
            data = r.json()

        if not isinstance(data, list):
            data = data.get("data", []) if isinstance(data, dict) else []

        result = []
        for item in data:
            fecha_str = item.get("fecha", "")
            precio_str = item.get("ultimo", item.get("cierre", ""))
            if not fecha_str or not precio_str:
                continue
            try:
                d = datetime.strptime(fecha_str.strip(), "%d/%m/%Y").date()
                precio_limpio = precio_str.replace(".", "").replace(",", ".")
                precio = float(precio_limpio)
                if precio > 0:
                    result.append({"fecha": d, "precio": round(precio, 2)})
            except (ValueError, AttributeError):
                continue

        print(f"[historial_real] Ambito {ticker}: {len(result)} puntos", flush=True)
        return sorted(result, key=lambda x: x["fecha"])

    except Exception as e:
        import traceback
        print(f"[historial_real] Ambito ERROR para {ticker}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        return []


# ─── CAFCI (FCI) ──────────────────────────────────────────────────────────────

def _descargar_cafci(fondo_id: int) -> List[Dict]:
    """
    Descarga cuotapartes históricas de CAFCI.
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
        print(f"[historial_real] CAFCI GET {url}", flush=True)
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "SimuladorCartera/2.0"})
            r.raise_for_status()
            data = r.json()

        rows = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            print(f"[historial_real] CAFCI fondo_id={fondo_id}: respuesta inesperada: {str(data)[:200]}", flush=True)
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

        print(f"[historial_real] CAFCI fondo_id={fondo_id}: {len(result)} puntos", flush=True)
        return sorted(result, key=lambda x: x["fecha"])

    except Exception as e:
        import traceback
        print(f"[historial_real] CAFCI ERROR para fondo_id={fondo_id}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        return []


# ─── Función principal ────────────────────────────────────────────────────────

def obtener_historial_real(ticker: str) -> List[Dict]:
    """
    Punto de entrada único. Devuelve historial de ~3 años para el ticker dado.
    Retorna [] si falla (el caller puede usar GBM como fallback).
    """
    print(f"[historial_real] obtener_historial_real({ticker})", flush=True)

    if ticker in _YFINANCE_MAP:
        datos = _descargar_yfinance(_YFINANCE_MAP[ticker])
        if datos:
            print(f"[historial_real] {ticker}: OK yfinance, {len(datos)} puntos", flush=True)
            return datos
        print(f"[historial_real] {ticker}: yfinance vacío → GBM fallback", flush=True)
        return []

    if ticker in _AMBITO_MAP:
        datos = _descargar_ambito(_AMBITO_MAP[ticker])
        if datos:
            print(f"[historial_real] {ticker}: OK Ambito, {len(datos)} puntos", flush=True)
            return datos
        print(f"[historial_real] {ticker}: Ambito vacío → GBM fallback", flush=True)
        return []

    if ticker in _CAFCI_MAP:
        datos = _descargar_cafci(_CAFCI_MAP[ticker])
        if datos:
            print(f"[historial_real] {ticker}: OK CAFCI, {len(datos)} puntos", flush=True)
            return datos
        print(f"[historial_real] {ticker}: CAFCI vacío → GBM fallback", flush=True)
        return []

    print(f"[historial_real] {ticker}: sin fuente conocida → GBM fallback", flush=True)
    return []
