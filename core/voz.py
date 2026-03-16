import asyncio
import edge_tts
import pvporcupine
import sounddevice as sd
import numpy as np
import whisper
import requests
import struct
import time
import os
from dotenv import load_dotenv
from pathlib import Path
from playsound3 import playsound

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# ─── Config ──────────────────────────────────────────────────────
PICOVOICE_KEY  = os.getenv("PICOVOICE_KEY", "")
VOICE_EDGE     = "pt-BR-FranciscaNeural"
WAKE_WORD_PATH = "assistente_pt_windows_v4_0_0.ppn"
MODEL_PATH     = "porcupine_params_pt.pv"
SERVIDOR_URL   = "http://localhost:8000/conversar"
OVERLAY_URL    = "http://127.0.0.1:3000"
SESSAO_ID      = "voz_local"
SAMPLE_RATE    = 16000
DURACAO_CMD    = 6

# ─── Estado global ───────────────────────────────────────────────
ouvindo_sempre = False

# ─── Inicializa ──────────────────────────────────────────────────
print("Carregando Whisper...")
modelo_whisper = whisper.load_model("base")

porcupine = pvporcupine.create(
    access_key=PICOVOICE_KEY,
    keyword_paths=[WAKE_WORD_PATH],
    model_path=MODEL_PATH
)

print("✓ Katarina pronta")

# ─── Overlay ─────────────────────────────────────────────────────
def overlay(evento: str, texto: str = "", expressao: str = "falando"):
    try:
        payload = {"evento": evento}
        if evento == "fala":
            payload["texto"] = texto
            payload["expressao"] = expressao
        requests.post(OVERLAY_URL, json=payload, timeout=1)
    except Exception:
        pass

def detectar_expressao(texto: str) -> str:
    t = texto.lower()
    if any(p in t for p in ["haha", "kkk", "engraçad", "brincad", "adorável"]):
        return "feliz"
    if any(p in t for p in ["não sei", "hmm", "deixa eu pensar", "interessante"]):
        return "pensativa"
    if any(p in t for p in ["erro", "problema", "falhou", "não consigo"]):
        return "seria"
    if any(p in t for p in ["nossa", "sério", "incrível", "que absurdo"]):
        return "surpresa"
    if any(p in t for p in ["claro", "óbvio", "como assim", "realmente"]):
        return "ironica"
    return "falando"

# ─── Falar com Edge TTS ──────────────────────────────────────────
async def _sintetizar(texto: str, caminho: str):
    tts = edge_tts.Communicate(texto, VOICE_EDGE)
    await tts.save(caminho)

def falar(texto: str):
    print(f"Katarina: {texto}")
    expressao = detectar_expressao(texto)
    overlay("fala", texto=texto, expressao=expressao)
    try:
        tmp_path = os.path.abspath("tmp_audio.mp3")
        asyncio.run(_sintetizar(texto, tmp_path))
        playsound(tmp_path)
        os.remove(tmp_path)
    except Exception as e:
        print(f"Erro TTS: {e}")
    finally:
        overlay("idle")

# ─── Gravar áudio ────────────────────────────────────────────────
def gravar_audio(duracao: int) -> np.ndarray:
    print("Ouvindo...")
    overlay("ouve")
    audio = sd.rec(
        int(duracao * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='float32',
        device=None
    )
    sd.wait()
    return audio.flatten()

def audio_tem_voz(audio: np.ndarray, threshold: float = 0.03) -> bool:
    return float(np.max(np.abs(audio))) > threshold

# ─── Transcrever ─────────────────────────────────────────────────
def transcrever(audio: np.ndarray) -> str:
    if not audio_tem_voz(audio):
        return ""
    resultado = modelo_whisper.transcribe(audio, language="pt")
    return resultado["text"].strip()

# ─── Chamar servidor ─────────────────────────────────────────────
def chamar_katarina(texto: str) -> str:
    try:
        resp = requests.post(SERVIDOR_URL, json={
            "sessao_id": SESSAO_ID,
            "texto": texto
        }, timeout=30)
        return resp.json().get("resposta", "")
    except Exception as e:
        print(f"Erro ao chamar servidor: {e}")
        return "Tô com problema técnico, tenta de novo."

# ─── Comandos de controle ────────────────────────────────────────
def checar_comando_controle(texto: str) -> bool:
    global ouvindo_sempre
    t = texto.lower().strip()

    if any(p in t for p in ["ligar assistente", "liga assistente", "modo contínuo", "modo continuo"]):
        ouvindo_sempre = True
        print("[Modo] Contínuo ATIVADO")
        falar("Modo contínuo ativado. Pode falar à vontade.")
        return True

    if any(p in t for p in ["pausar assistente", "pausa assistente", "parar assistente", "para assistente", "desligar assistente"]):
        ouvindo_sempre = False
        print("[Modo] Contínuo PAUSADO")
        falar("Pausando. Me chame quando precisar.")
        return True

    return False

# ─── Loop principal ──────────────────────────────────────────────
def main():
    global ouvindo_sempre

    print("─" * 40)
    print("  Katarina — Modo Voz")
    print("  Fale 'Assistente' para ativar")
    print("  'ligar assistente' → modo contínuo")
    print("  'pausar assistente' → volta ao normal")
    print("  Ctrl+C para sair")
    print("─" * 40)

    frame_length = porcupine.frame_length

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='int16',
        device=None,
        blocksize=frame_length
    ) as stream:
        while True:
            try:
                pcm, _ = stream.read(frame_length)
                pcm = struct.unpack_from("h" * frame_length, pcm)
                resultado = porcupine.process(pcm)

                ativou_wake_word = resultado >= 0

                if ativou_wake_word or ouvindo_sempre:

                    if ativou_wake_word and not ouvindo_sempre:
                        print("\n✓ Wake word detectada!")
                        falar("Oi, pode falar.")

                    audio_cmd = gravar_audio(DURACAO_CMD)
                    comando = transcrever(audio_cmd)

                    if not comando or len(comando) < 3:
                        overlay("idle")
                        continue

                    print(f"Você: {comando}")

                    if checar_comando_controle(comando):
                        continue

                    resposta = chamar_katarina(comando)
                    if resposta:
                        falar(resposta)
                    else:
                        overlay("idle")

            except KeyboardInterrupt:
                print("\nSaindo...")
                break
            except Exception as e:
                print(f"Erro: {e}")
                overlay("idle")
                time.sleep(0.5)

    porcupine.delete()

if __name__ == "__main__":
    main()