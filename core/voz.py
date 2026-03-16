import asyncio
import edge_tts
import pvporcupine
import sounddevice as sd
import numpy as np
import requests
import struct
import time
import os
import threading
from groq import Groq
from dotenv import load_dotenv
from pathlib import Path
from playsound3 import playsound
from scipy.io.wavfile import write
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# ─── Config ──────────────────────────────────────────────────────
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

# Porta local que o servidor.py chama para pedir síntese de voz
VOZ_SERVER_PORT = 8001

client    = Groq(api_key=GROQ_API_KEY)
porcupine = pvporcupine.create(
    access_key=PICOVOICE_KEY,
    keyword_paths=[WAKE_WORD_PATH],
    model_path=MODEL_PATH
)

# ─── Estado global ───────────────────────────────────────────────
ouvindo_sempre = False
# Lock para evitar duas falas ao mesmo tempo (servidor + voz.py)
_fala_lock = threading.Lock()

# ─── Funções de Suporte ──────────────────────────────────────────
def overlay(evento: str, texto: str = "", expressao: str = "falando"):
    try:
        payload = {"evento": evento}
        if evento == "fala":
            payload["texto"]    = texto
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
    if any(p in t for p in ["haha", "kkk", "engraçado"]):                 return "feliz"
    if any(p in t for p in ["não sei", "hmm", "pensar"]):                 return "pensativa"
    return "falando"

async def _sintetizar(texto: str, caminho: str):
    texto_preparado = " . . " + texto
    tts = edge_tts.Communicate(texto_preparado, VOICE_EDGE)
    await tts.save(caminho)

def falar(texto: str):
    """Sintetiza voz e anima o overlay. Thread-safe via lock."""
    with _fala_lock:
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

# ─── Servidor HTTP local de voz (porta 8001) ─────────────────────
# O servidor.py chama POST http://localhost:8001/falar {"texto": "..."}
# para pedir que a Katarina fale algo (comentários de tela, alertas, proativo)
class VozHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silencia logs do HTTP server

    def do_POST(self):
        if self.path == "/falar":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                data  = json.loads(body)
                texto = data.get("texto", "").strip()
                if texto:
                    # Roda em thread separada para não bloquear o HTTP handler
                    threading.Thread(target=falar, args=(texto,), daemon=True).start()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok": true}')
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"erro": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

def iniciar_servidor_voz():
    server = HTTPServer(("127.0.0.1", VOZ_SERVER_PORT), VozHandler)
    print(f"✓ Servidor de voz ouvindo na porta {VOZ_SERVER_PORT}")
    server.serve_forever()

# ─── Captura Dinâmica (VAD) ──────────────────────────────────────
def gravar_audio(duracao_maxima=8):
    print("🎤 Ouvindo...")
    overlay("ouve")
    CHUNK_SIZE      = 1024
    THRESHOLD       = 0.05
    SILENCE_LIMIT   = int(1.2 * SAMPLE_RATE / CHUNK_SIZE)
    audio_buffer    = []
    falando         = False
    frames_silencio = 0

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32') as stream:
        while True:
            chunk, _     = stream.read(CHUNK_SIZE)
            volume_norm  = np.max(np.abs(chunk))

            if volume_norm > THRESHOLD:
                if not falando:
                    falando = True
                audio_buffer.append(chunk)
                frames_silencio = 0
            elif falando:
                audio_buffer.append(chunk)
                frames_silencio += 1
                if frames_silencio > SILENCE_LIMIT:
                    break

            if len(audio_buffer) > (duracao_maxima * SAMPLE_RATE / CHUNK_SIZE):
                break

    return np.concatenate(audio_buffer).flatten() if audio_buffer else None

# ─── Transcrição Groq ────────────────────────────────────────────
def transcrever_audio_groq(audio_data):
    if audio_data is None:
        return ""
    try:
        write(FILE_TEMP_AUDIO, SAMPLE_RATE, audio_data)
        with open(FILE_TEMP_AUDIO, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(FILE_TEMP_AUDIO, file.read()),
                model="whisper-large-v3-turbo",
                response_format="text",
                language="pt",
                prompt="Katarina. Assistente virtual."
            )
        if os.path.exists(FILE_TEMP_AUDIO):
            os.remove(FILE_TEMP_AUDIO)

        texto = transcription.strip()
        lixo  = ["E aí", "Oi.", "Obrigado.", "Você", "Legendas por"]
        if texto in lixo or len(texto) <= 2:
            return ""
        return texto
    except Exception as e:
        print(f"Erro Transcrição: {e}")
        return ""

# ─── Loop Principal ──────────────────────────────────────────────
def main():
    global ouvindo_sempre

    # Sobe o servidor de voz em thread daemon antes do loop principal
    threading.Thread(target=iniciar_servidor_voz, daemon=True).start()

    print("✓ Katarina online. Fale 'Assistente'...")

    em_conversa  = False
    frame_length = porcupine.frame_length

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', blocksize=frame_length) as stream:
        while True:
            try:
                # ESTADO A: Esperando Wake Word
                if not em_conversa and not ouvindo_sempre:
                    pcm, _ = stream.read(frame_length)
                    pcm    = struct.unpack_from("h" * frame_length, pcm)
                    if porcupine.process(pcm) >= 0:
                        print("✨ Wake word detectada!")
                        falar("Oi, pode falar.")
                        em_conversa = True
                    else:
                        continue

                # ESTADO B: Diálogo Ativo
                print("🎤 Escuta ativa...")
                audio_cmd = gravar_audio()

                if audio_cmd is None:
                    print("...silêncio detectado. Voltando para espera.")
                    em_conversa = False
                    overlay("idle")
                    continue

                comando = transcrever_audio_groq(audio_cmd)

                if not comando or len(comando.strip()) < 2:
                    print("...comando não compreendido.")
                    if not ouvindo_sempre:
                        em_conversa = False
                    overlay("idle")
                    continue

                print(f"Você: {comando}")

                # Comandos de sistema
                if "ligar assistente" in comando.lower():
                    ouvindo_sempre = True
                    falar("Modo contínuo ativado.")
                    continue
                elif "pausar assistente" in comando.lower():
                    ouvindo_sempre = False
                    em_conversa    = False
                    falar("Modo contínuo desativado.")
                    continue

                # Resposta da IA
                try:
                    resp_json = requests.post(
                        SERVIDOR_URL,
                        json={"sessao_id": SESSAO_ID, "texto": comando},
                        timeout=15
                    ).json()
                    resposta = resp_json.get("resposta", "")
                    if resposta:
                        falar(resposta)
                        em_conversa = True
                    else:
                        em_conversa = False
                except Exception as e:
                    print(f"Erro no servidor: {e}")
                    falar("Houve um erro no meu cérebro agora.")
                    em_conversa = False

            except Exception as e:
                print(f"Erro Crítico no Loop: {e}")
                overlay("idle")
                em_conversa = False
                time.sleep(1)

if __name__ == "__main__":
    main()