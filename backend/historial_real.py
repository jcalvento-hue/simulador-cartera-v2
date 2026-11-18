"""
Descarga de historial real de precios para los instrumentos del simulador.

Fuentes:
  - Ambito Financiero → acciones argentinas, CEDEARs y bonos soberanos
  - CAFCI             → FCI (bloqueado desde Render → GBM fallback)

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

# Mapeo ticker simulador → ticker Ambito (acciones argentinas)
_AMBITO_ACCIONES: Dict[str, str] = {
    "GGAL":  "GGAL",
    "YPF":   "YPFD",   # YPF en BCBA cotiza como YPFD
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

# Mapeo ticker simulador → ticker Ambito (CEDEARs)
_AMBITO_CEDEARS: Dict[str, str] = {
    "AAPL":  "AAPL",
    "GOOGL": "GOOGL",
    "AMZN":  "AMZN",
    "MSFT":  "MSFT",
    "TSLA":  "TSLA",
    "BRKB":  "BRKB",
}

# Mapeo ticker simulador → ticker Ambito (bonos)
_AMBITO_BONOS: Dict[str, str] = {
    "AL30": "AL30",
    "GD30": "GD30",
    "AL35": "AL35",
    "AE38": "AE38",
    "TX26": "TX26",
    "T2X5": "T2X5",
}

# FCI: bloqueado desde Render (CAFCI da 403) → siempre GBM fallback
_FCI_TICKERS = {"FCICONV", "FCIMOD", "FCIAGR"}


# ─── Ambito (función genérica) ────────────────────────────────────────────────

def _descargar_ambito(tipo: str, ticker: str) -> List[Dict]:
    """
    Descarga historial desde Ambito Financiero.
    tipo: "acciones" | "cedears" | "bonos"
    Endpoint: https://mercados.ambito.com/{tipo}/{ticker}/historico-general/{DESDE}/{HASTA}
    Responde JSON lista: [{"fecha": "DD/MM/YYYY", "ultimo": "1234,56"}, ...]
    """
    try:
        fecha_fin = date.today()
        fecha_ini = fecha_fin - timedelta(days=365 * AÑOS_HISTORIAL)
        url = (
            f"https://mercados.ambito.com/{tipo}/{ticker}/historico-general/"
            f"{fecha_ini.strftime('%d-%m-%Y')}/{fecha_fin.strftime('%d-%m-%Y')}"
        )
        print(f"[historial_real] Ambito GET {url}", flush=True)

        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            r = client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            })
            r.raise_for_status()
            data = r.json()

        # Puede devolver lista directa o {"data": [...]}
        if isinstance(data, dict):
            data = data.get("data", [])
        if not isinstance(data, list):
            print(f"[historial_real] Ambito {ticker}: respuesta inesperada: {str(data)[:200]}", flush=True)
            return []

        result = []
        for item in data:
            fecha_str = item.get("fecha", "")
            precio_str = item.get("ultimo", item.get("cierre", ""))
            if not fecha_str or not precio_str:
                continue
            try:
                # Ambito usa DD/MM/YYYY
                d = datetime.strptime(fecha_str.strip(), "%d/%m/%Y").date()
                # Precio puede ser "1.234,56" (miles=punto, decimal=coma)
                precio_limpio = str(precio_str).replace(".", "").replace(",", ".")
                precio = float(precio_limpio)
                if precio > 0:
                    result.append({"fecha": d, "precio": round(precio, 2)})
            except (ValueError, AttributeError):
                continue

        result = sorted(result, key=lambda x: x["fecha"])
        print(f"[historial_real] Ambito {tipo}/{ticker}: {len(result)} puntos", flush=True)
        return result

    except Exception as e:
        import traceback
        print(f"[historial_real] Ambito ERROR {tipo}/{ticker}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        return []


# ─── Función principal ────────────────────────────────────────────────────────

def obtener_historial_real(ticker: str) -> List[Dict]:
    """
    Punto de entrada único. Devuelve historial de ~3 años para el ticker dado.
    Retorna [] si falla (el caller usa GBM como fallback).
    """
    print(f"[historial_real] obtener_historial_real({ticker})", flush=True)

    # Acciones argentinas
    if ticker in _AMBITO_ACCIONES:
        datos = _descargar_ambito("acciones", _AMBITO_ACCIONES[ticker])
        if datos:
            print(f"[historial_real] {ticker}: OK Ambito acciones, {len(datos)} puntos", flush=True)
            return datos
        print(f"[historial_real] {ticker}: Ambito vacío → GBM fallback", flush=True)
        return []

    # CEDEARs
    if ticker in _AMBITO_CEDEARS:
        datos = _descargar_ambito("cedears", _AMBITO_CEDEARS[ticker])
        if datos:
            print(f"[historial_real] {ticker}: OK Ambito cedears, {len(datos)} puntos", flush=True)
            return datos
        print(f"[historial_real] {ticker}: Ambito cedears vacío → GBM fallback", flush=True)
        return []

    # Bonos
    if ticker in _AMBITO_BONOS:
        datos = _descargar_ambito("bonos", _AMBITO_BONOS[ticker])
        if datos:
            print(f"[historial_real] {ticker}: OK Ambito bonos, {len(datos)} puntos", flush=True)
            return datos
        print(f"[historial_real] {ticker}: Ambito bonos vacío → GBM fallback", flush=True)
        return []

    # FCI: sin fuente disponible desde Render
    if ticker in _FCI_TICKERS:
        print(f"[historial_real] {ticker}: FCI sin fuente disponible → GBM fallback", flush=True)
        return []

    print(f"[historial_real] {ticker}: ticker desconocido → GBM fallback", flush=True)
    return []
