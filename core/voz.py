import asyncio
import edge_tts
import pvporcupine
import sounddevice as sd
import numpy as np
import requests
import struct
import time
import os
import re
import threading
from groq import Groq
from dotenv import load_dotenv
from pathlib import Path
from playsound3 import playsound
from scipy.io.wavfile import write
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

import estado_global

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# ─── Config ───────────────────────────────────────────────────────────────────
PICOVOICE_KEY   = os.getenv("PICOVOICE_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
VOICE_EDGE      = "pt-BR-FranciscaNeural"
WAKE_WORD_PATH  = "assistente_pt_windows_v4_0_0.ppn"
MODEL_PATH      = "porcupine_params_pt.pv"
SERVIDOR_URL    = "http://localhost:8000/conversar"
OVERLAY_URL     = "http://127.0.0.1:3000"
SESSAO_ID       = "voz_local"
SAMPLE_RATE     = 16000
FILE_TEMP_AUDIO = "audio_temp.wav"
VOZ_SERVER_PORT = 8001

client    = Groq(api_key=GROQ_API_KEY)
porcupine = pvporcupine.create(
    access_key=PICOVOICE_KEY,
    keyword_paths=[WAKE_WORD_PATH],
    model_path=MODEL_PATH
)

_fala_lock = threading.Lock()

# ─── Humanização do texto ─────────────────────────────────────────────────────
def humanizar_texto(texto: str) -> str:
    """Limpa markdown e normaliza pausas para soar mais natural."""
    texto = re.sub(r'\.{3,}', ', ', texto)
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'#+\s*', '', texto)
    return texto.strip()

# ─── Overlay ──────────────────────────────────────────────────────────────────
def overlay(evento: str, texto: str = "", expressao: str = "falando"):
    try:
        payload = {"evento": evento}
        if evento == "fala":
            payload["texto"]     = texto
            payload["expressao"] = expressao
        requests.post(OVERLAY_URL, json=payload, timeout=1)
    except Exception:
        pass

def detectar_expressao(texto: str) -> str:
    t = texto.lower()
    if any(p in t for p in ["sério isso", "lá vem você", "kk", "kkk"]): return "ironica"
    if any(p in t for p in ["ótimo", "feliz", "massa", "show"]):          return "feliz"
    if any(p in t for p in ["errado", "problema", "cuidado"]):            return "brava"
    if any(p in t for p in ["como assim", "espera", "nossa"]):            return "surpresa"
    if any(p in t for p in ["talvez", "não sei", "difícil"]):             return "pensativa"
    if any(p in t for p in ["entendo", "tô aqui", "ouço"]):               return "seria"
    return "falando"

# ─── Síntese de voz ───────────────────────────────────────────────────────────
async def _sintetizar(texto: str, caminho: str):
    texto_preparado = " . . " + texto
    tts = edge_tts.Communicate(texto_preparado, VOICE_EDGE)
    await tts.save(caminho)

def falar(texto: str):
    """Sintetiza e reproduz. Silencioso se pausada."""
    if estado_global.esta_pausada():
        return
    with _fala_lock:
        texto = humanizar_texto(texto)
        print(f"Katarina: {texto}")
        expressao = detectar_expressao(texto)
        overlay("fala", texto=texto, expressao=expressao)
        try:
            tmp_path = os.path.abspath("tmp_audio.mp3")
            asyncio.run(_sintetizar(texto, tmp_path))
            time.sleep(0.2)
            playsound(tmp_path)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception as e:
            print(f"Erro TTS: {e}")
        finally:
            overlay("idle")

# ─── Servidor HTTP local de voz (porta 8001) ──────────────────────────────────
class VozHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        if self.path == "/falar":
            try:
                texto = json.loads(body).get("texto", "").strip()
                if texto:
                    threading.Thread(target=falar, args=(texto,), daemon=True).start()
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_response(400); self.end_headers()
                self.wfile.write(json.dumps({"erro": str(e)}).encode())

        elif self.path == "/pausar":
            pausado = estado_global.toggle()
            print(f"[VOZ] Katarina {'pausada' if pausado else 'ativa'}")
            if not pausado:
                threading.Thread(target=falar, args=("Tô de volta.",), daemon=True).start()
            else:
                overlay("idle")
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({"pausada": pausado}).encode())

        else:
            self.send_response(404); self.end_headers()

def iniciar_servidor_voz():
    HTTPServer(("127.0.0.1", VOZ_SERVER_PORT), VozHandler).serve_forever()

# ─── Captura dinâmica (VAD) ───────────────────────────────────────────────────
def gravar_audio(duracao_maxima=8):
    print("Ouvindo...")
    overlay("ouve")
    CHUNK       = 1024
    THRESHOLD   = 0.05
    SIL_LIMIT   = int(1.2 * SAMPLE_RATE / CHUNK)
    buf, ativo, sil = [], False, 0

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32') as stream:
        while True:
            chunk, _ = stream.read(CHUNK)
            vol = np.max(np.abs(chunk))
            if vol > THRESHOLD:
                if not ativo: ativo = True
                buf.append(chunk); sil = 0
            elif ativo:
                buf.append(chunk); sil += 1
                if sil > SIL_LIMIT: break
            if len(buf) > (duracao_maxima * SAMPLE_RATE / CHUNK): break

    return np.concatenate(buf).flatten() if buf else None

# ─── Transcrição Groq ─────────────────────────────────────────────────────────
def transcrever(audio):
    if audio is None: return ""
    try:
        write(FILE_TEMP_AUDIO, SAMPLE_RATE, audio)
        with open(FILE_TEMP_AUDIO, "rb") as f:
            t = client.audio.transcriptions.create(
                file=(FILE_TEMP_AUDIO, f.read()),
                model="whisper-large-v3-turbo",
                response_format="text",
                language="pt",
                prompt="Katarina. Assistente virtual."
            )
        if os.path.exists(FILE_TEMP_AUDIO): os.remove(FILE_TEMP_AUDIO)
        texto = t.strip()
        if texto in ["E aí", "Oi.", "Obrigado.", "Você", "Legendas por"] or len(texto) <= 2:
            return ""
        return texto
    except Exception as e:
        print(f"Erro transcrição: {e}"); return ""

# ─── Loop Principal ───────────────────────────────────────────────────────────
def main():
    ouvindo_sempre = False
    threading.Thread(target=iniciar_servidor_voz, daemon=True).start()
    print("Katarina online. Fale 'Assistente'...")

    em_conversa  = False
    frame_length = porcupine.frame_length

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', blocksize=frame_length) as stream:
        while True:
            try:
                # Pausada — só escuta wake word pra retomar
                if estado_global.esta_pausada():
                    pcm, _ = stream.read(frame_length)
                    pcm    = struct.unpack_from("h" * frame_length, pcm)
                    if porcupine.process(pcm) >= 0:
                        audio = gravar_audio()
                        if audio is not None:
                            cmd = transcrever(audio).lower()
                            if any(p in cmd for p in ["voltar", "volta", "retomar", "continuar"]):
                                estado_global.retomar()
                                em_conversa = False
                                falar("Tô de volta.")
                    continue

                # ESTADO A: Esperando Wake Word
                if not em_conversa and not ouvindo_sempre:
                    pcm, _ = stream.read(frame_length)
                    pcm    = struct.unpack_from("h" * frame_length, pcm)
                    if porcupine.process(pcm) >= 0:
                        print("Wake word detectada!")
                        falar("Oi, pode falar.")
                        em_conversa = True
                    else:
                        continue

                # ESTADO B: Diálogo Ativo
                audio_cmd = gravar_audio()

                if audio_cmd is None:
                    em_conversa = False; overlay("idle"); continue

                comando = transcrever(audio_cmd)

                if not comando or len(comando.strip()) < 2:
                    if not ouvindo_sempre: em_conversa = False
                    overlay("idle"); continue

                print(f"Você: {comando}")
                estado_global.registrar_interacao()

                # Comandos de sistema
                if "ligar assistente" in comando.lower():
                    ouvindo_sempre = True
                    falar("Modo contínuo ativado.")
                    continue

                if any(p in comando.lower() for p in ["assistente descansar", "pausar assistente", "parar assistente", "assistente dormir"]):
                    estado_global.pausar()
                    ouvindo_sempre = False; em_conversa = False
                    overlay("idle"); print("[VOZ] Pausada."); continue

                # Resposta da IA
                try:
                    resp = requests.post(
                        SERVIDOR_URL,
                        json={"sessao_id": SESSAO_ID, "texto": comando},
                        timeout=15
                    ).json()
                    resposta = resp.get("resposta", "")
                    if resposta:
                        falar(resposta); em_conversa = True
                    else:
                        em_conversa = False
                except Exception as e:
                    print(f"Erro servidor: {e}")
                    falar("Deu um problema aqui, tenta de novo.")
                    em_conversa = False

            except Exception as e:
                print(f"Erro crítico: {e}")
                overlay("idle"); em_conversa = False; time.sleep(1)

if __name__ == "__main__":
    main()