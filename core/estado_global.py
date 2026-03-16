import threading
import datetime
import requests

# ── Flag de pausa global ──────────────────────────────────────────────────────
_lock   = threading.Lock()
_pausada = False

def esta_pausada() -> bool:
    with _lock:
        return _pausada

def pausar():
    global _pausada
    with _lock:
        _pausada = True

def retomar():
    global _pausada
    with _lock:
        _pausada = False

def toggle() -> bool:
    """Alterna pausa. Retorna True se ficou pausada."""
    global _pausada
    with _lock:
        _pausada = not _pausada
        return _pausada

# ── Timestamp da última interação (compartilhado com loop_autonomo) ───────────
ultima_interacao: datetime.datetime = datetime.datetime.now()

def registrar_interacao():
    global ultima_interacao
    ultima_interacao = datetime.datetime.now()