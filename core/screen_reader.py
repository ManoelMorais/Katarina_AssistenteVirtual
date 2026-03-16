"""
core/screen_reader.py
Fase 4 — Leitura de tela da Katarina

Dois loops paralelos:
  1. Periódico      — captura a cada CAPTURE_INTERVAL segundos
  2. Mudança janela — captura quando a janela ativa muda

Instalação (Windows):
  1. Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
     Durante a instalação marque: Portuguese + English
     Confirme que está no PATH: tesseract --version
  2. pip install mss pytesseract pillow pygetwindow
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime
from typing import Callable, Optional

import mss
import pytesseract
from PIL import Image, ImageFilter

from screen_context import ScreenContext

log = logging.getLogger("fase4")

# ── Configurações ──────────────────────────────────────────────────────────────
CAPTURE_INTERVAL      = 30    # segundos entre capturas periódicas
CHANGE_CHECK_INTERVAL = 2     # segundos entre checks de janela ativa
MIN_TEXT_LENGTH       = 40    # descarta screenshots com pouco texto

# Palavras que disparam alerta imediato (sem esperar o LLM)
ALERT_KEYWORDS = [
    "erro", "error", "exception", "traceback", "critical",
    "falhou", "failed", "denied", "warning", "atenção",
    "unauthorized", "timeout", "crash",
]

# Intenções de leitura de tela — detectadas no /conversar
SCREEN_KEYWORDS = [
    "o que você vê", "o que está na tela", "o que tem na tela",
    "leia a tela", "veja a tela", "tem erro", "o que está acontecendo",
    "what do you see", "read the screen",
]


# ── Prompt de análise ──────────────────────────────────────────────────────────
ANALYSIS_PROMPT = """
Você é o módulo de visão da Katarina, assistente virtual pessoal.
Receberá texto extraído da tela do usuário via OCR e deve decidir a melhor ação.

Responda APENAS com JSON (sem markdown, sem explicação fora do JSON):
{
  "action": "silent" | "comment" | "alert",
  "message": "mensagem em português, tom da Katarina, máx 2 frases curtas",
  "reason": "motivo interno (não falar pro usuário)"
}

Regras:
- "silent": conteúdo mundano, sem novidade. message pode ser vazio.
- "comment": algo interessante, curioso ou útil para comentar levemente.
- "alert": erro, exceção, falha, notificação crítica — prioridade máxima.
- Nunca invente informações além do que está no texto.
- Tom: direto, levemente sarcástico quando cabível, mas sem ser repetitivo.
""".strip()


# ── Utilitários ────────────────────────────────────────────────────────────────
def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _clean_ocr(raw: str) -> str:
    """Remove ruído típico de OCR e normaliza o texto."""
    text = re.sub(r"[^\x20-\x7E\u00C0-\u024F\n]", "", raw)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return text.strip()


def _has_alert_keyword(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in ALERT_KEYWORDS)


def _get_active_window() -> str:
    """Retorna o título da janela ativa no Windows."""
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        return w.title if w else "Desconhecida"
    except Exception:
        return "Desconhecida"


def is_screen_question(text: str) -> bool:
    """Detecta se o usuário está perguntando sobre a tela."""
    lower = text.lower()
    return any(kw in lower for kw in SCREEN_KEYWORDS)


# ── Captura e OCR ──────────────────────────────────────────────────────────────
def capture_and_ocr(monitor_index: int = 1, lang: str = "por+eng") -> Optional[dict]:
    """
    Captura a tela e extrai texto via OCR.
    Retorna dict com text_hash, clean_text, window_title — ou None se texto insuficiente.
    """
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[monitor_index]
            raw_img = sct.grab(monitor)
            image = Image.frombytes("RGB", raw_img.size, raw_img.bgra, "raw", "BGRX")

        # Pré-processamento leve para melhorar acurácia
        gray  = image.convert("L")
        sharp = gray.filter(ImageFilter.SHARPEN)

        raw_text  = pytesseract.image_to_string(sharp, lang=lang, config="--psm 3 --oem 3")
        clean     = _clean_ocr(raw_text)

        if len(clean) < MIN_TEXT_LENGTH:
            return None

        return {
            "clean_text":   clean,
            "text_hash":    _text_hash(clean),
            "window_title": _get_active_window(),
            "timestamp":    datetime.now(),
        }
    except Exception as e:
        log.error(f"Erro na captura/OCR: {e}")
        return None


# ── Análise LLM ────────────────────────────────────────────────────────────────
def analyze_screen(capture: dict, groq_client) -> dict:
    """
    Envia o texto da tela pro Groq e recebe a decisão de ação.
    groq_client = instância já existente do Groq em servidor.py
    """
    import json
    prompt = (
        f"Janela ativa: {capture['window_title']}\n\n"
        f"Texto na tela:\n{capture['clean_text'][:2000]}"
    )
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": ANALYSIS_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=300,
            temperature=0.4,
        )
        raw = resp.choices[0].message.content.strip()
        return json.loads(raw)
    except Exception as e:
        log.warning(f"Análise LLM falhou: {e}")
        return {"action": "silent", "message": "", "reason": str(e)}


def answer_about_screen(question: str, ctx: ScreenContext, groq_client) -> str:
    """
    Resposta sob demanda — chamada quando is_screen_question() retornar True.
    Retorna o texto da resposta para ser enviado normalmente pelo /conversar.
    """
    if not ctx.has_content():
        return "Ainda não capturei nada da tela — tente novamente em instantes."

    prompt = (
        f"Janela ativa: {ctx.current_window}\n\n"
        f"Texto visível na tela:\n{ctx.current_text[:2000]}\n\n"
        f"Pergunta do usuário: {question}"
    )
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": (
                    "Você é a Katarina. Responda à pergunta do usuário com base "
                    "APENAS no texto da tela fornecido. Seja direta e objetiva."
                )},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.5,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Não consegui analisar a tela agora: {e}"


# ── Salvar no Supabase ─────────────────────────────────────────────────────────
def save_screen_capture(capture: dict, action: str, message: str, supabase_client):
    """Persiste a captura para uso futuro na Fase 5."""
    try:
        supabase_client.table("screen_captures").insert({
            "timestamp":    capture["timestamp"].isoformat(),
            "window_title": capture["window_title"],
            "clean_text":   capture["clean_text"][:3000],
            "text_hash":    capture["text_hash"],
            "action":       action,
            "message":      message,
        }).execute()
    except Exception as e:
        log.warning(f"Supabase screen_captures indisponível: {e}")


# ── ScreenReader ───────────────────────────────────────────────────────────────
class ScreenReader:
    """
    Gerencia os dois loops de captura em paralelo.

    Uso em servidor.py (no startup):
        reader = ScreenReader(
            groq_client   = groq_client,
            supabase      = supabase,
            screen_context= screen_ctx,
            on_alert      = callback_voz_alerta,
            on_comment    = callback_voz_comentario,
        )
        asyncio.create_task(reader.start())
    """

    def __init__(
        self,
        groq_client,
        supabase,
        screen_context: ScreenContext,
        on_alert:   Optional[Callable[[str], None]] = None,
        on_comment: Optional[Callable[[str], None]] = None,
        monitor_index: int = 1,
        lang: str = "por+eng",
    ):
        self.groq          = groq_client
        self.supabase      = supabase
        self.ctx           = screen_context
        self.on_alert      = on_alert   or (lambda m: log.info(f"[ALERTA] {m}"))
        self.on_comment    = on_comment or (lambda m: log.info(f"[COMENTÁRIO] {m}"))
        self.monitor_index = monitor_index
        self.lang          = lang

        self._last_hash   = ""
        self._last_window = ""
        self._running     = False

    async def start(self):
        self._running = True
        log.info("Fase 4 iniciada.")
        await asyncio.gather(
            self._periodic_loop(),
            self._window_change_loop(),
        )

    def stop(self):
        self._running = False

    async def _periodic_loop(self):
        while self._running:
            await self._process(source="periódico")
            await asyncio.sleep(CAPTURE_INTERVAL)

    async def _window_change_loop(self):
        while self._running:
            title = _get_active_window()
            if title != self._last_window:
                log.info(f"Janela mudou: {self._last_window!r} → {title!r}")
                self._last_window = title
                await self._process(source="mudança de janela")
            await asyncio.sleep(CHANGE_CHECK_INTERVAL)

    async def _process(self, source: str = ""):
        loop    = asyncio.get_event_loop()
        capture = await loop.run_in_executor(
            None, capture_and_ocr, self.monitor_index, self.lang
        )
        if not capture:
            return

        # Deduplicação — ignora se o conteúdo não mudou
        if capture["text_hash"] == self._last_hash:
            return
        self._last_hash = capture["text_hash"]

        log.info(f"[{source}] {capture['window_title']!r} — {len(capture['clean_text'])} chars")

        # Atualiza contexto silencioso
        self.ctx.current_text   = capture["clean_text"]
        self.ctx.current_window = capture["window_title"]
        self.ctx.last_update    = capture["timestamp"]
        self.ctx.history.append(capture)
        if len(self.ctx.history) > 20:
            self.ctx.history.pop(0)

        # Alerta rápido por keyword (sem esperar LLM)
        if _has_alert_keyword(capture["clean_text"]):
            msg = f"Tem algo parecendo um erro na janela {capture['window_title']}. Quer que eu veja?"
            self.on_alert(msg)
            save_screen_capture(capture, "alert_keyword", msg, self.supabase)
            return

        # Análise LLM
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, analyze_screen, capture, self.groq)
        action  = result.get("action", "silent")
        message = result.get("message", "")

        if action == "alert" and message:
            self.on_alert(message)
        elif action == "comment" and message:
            self.on_comment(message)
        # "silent" → só atualiza contexto, não fala nada

        save_screen_capture(capture, action, message, self.supabase)