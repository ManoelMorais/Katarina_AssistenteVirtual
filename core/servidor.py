from fastapi import FastAPI
from pydantic import BaseModel
from groq import Groq
from supabase import create_client
from sentence_transformers import SentenceTransformer
import os, sys, datetime, httpx, random
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─── Config ──────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'config'))
from config import *

app = FastAPI()

# ─── Clientes ────────────────────────────────────────────────────
groq_client    = Groq(api_key=GROQ_API_KEY)
supabase       = create_client(SUPABASE_URL, SUPABASE_KEY)
encoder        = SentenceTransformer('all-MiniLM-L6-v2')
scheduler      = AsyncIOScheduler()
historicos     = {}

# ─── Perfil ──────────────────────────────────────────────────────
def carregar_perfil():
    with open(PERFIL_PATH, "r", encoding="utf-8") as f:
        return f.read()

perfil = carregar_perfil()

# ─── Memória ─────────────────────────────────────────────────────
def salvar_memoria(sessao_id: str, role: str, texto: str):
    embedding = encoder.encode(texto).tolist()
    supabase.table("memorias").insert({
        "sessao_id": sessao_id,
        "role": role,
        "texto": f"[{role.upper()}] {texto}",
        "embedding": embedding,
        "timestamp": datetime.datetime.now().isoformat()
    }).execute()

def buscar_memorias(sessao_id: str, texto: str, n: int = 5) -> str:
    try:
        embedding = encoder.encode(texto).tolist()
        result = supabase.rpc("buscar_memorias", {
            "query_embedding": embedding,
            "match_count": n,
            "sessao_filter": sessao_id
        }).execute()
        if result.data:
            return "\n".join([r["texto"] for r in result.data])
        return ""
    except Exception:
        return ""

# ─── Expressão ───────────────────────────────────────────────────
def classificar_expressao(texto: str) -> str:
    t = texto.lower()
    if any(p in t for p in ["sério isso", "lá vem você", "kk", "kkk", "ironi"]):
        return "ironica"
    if any(p in t for p in ["que ótimo", "feliz", "massa", "show"]):
        return "feliz"
    if any(p in t for p in ["não concordo", "errado", "problema", "cuidado"]):
        return "brava"
    if any(p in t for p in ["como assim", "espera", "sério?", "nossa"]):
        return "surpresa"
    if any(p in t for p in ["pensando", "talvez", "não sei", "difícil"]):
        return "pensativa"
    if any(p in t for p in ["entendo", "tô aqui", "pode falar", "ouço"]):
        return "seria"
    return "falando"

# ─── Overlay ─────────────────────────────────────────────────────
async def avisar_overlay(evento: str, texto: str = "", expressao: str = "falando"):
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            await client.post(OVERLAY_URL, json={
                "evento": evento,
                "texto": texto,
                "expressao": expressao
            })
    except Exception:
        pass

# ─── System prompt ───────────────────────────────────────────────
system_prompt = f"{SYSTEM_PROMPT}\n\nO perfil dele:\n---\n{perfil}\n---"

# ─── Proativo ────────────────────────────────────────────────────
mensagens_proativas = [
    ("Ei, tô aqui. Sumiu.", "ironica"),
    ("Tô te observando.", "seria"),
    ("Oi. Só passando.", "feliz"),
    ("Ainda vivo aí?", "ironica"),
    ("Lembrei de você.", "neutra"),
    ("Tá bem?", "seria"),
]

async def aparicao_proativa():
    texto, expressao = random.choice(mensagens_proativas)
    await avisar_overlay("fala", texto, expressao)

# ─── Startup ─────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    scheduler.add_job(aparicao_proativa, 'interval', minutes=TEMPO_PROATIVO_MINUTOS)
    scheduler.start()

# ─── Endpoint ────────────────────────────────────────────────────
class Mensagem(BaseModel):
    sessao_id: str
    texto: str

@app.post("/conversar")
async def conversar(msg: Mensagem):
    sessao_id = msg.sessao_id
    texto     = msg.texto

    await avisar_overlay("ouve")

    if sessao_id not in historicos:
        historicos[sessao_id] = [{"role": "system", "content": system_prompt}]

    historico        = historicos[sessao_id]
    memorias         = buscar_memorias(sessao_id, texto)
    historico_mem    = list(historico)

    if memorias:
        historico_mem.append({
            "role": "system",
            "content": f"Memórias relevantes:\n{memorias}"
        })

    historico_mem.append({"role": "user", "content": texto})

    resposta = groq_client.chat.completions.create(
        model=MODELO,
        messages=historico_mem,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE
    )
    texto_resposta = resposta.choices[0].message.content

    if texto_resposta:
        historico.append({"role": "user", "content": texto})
        historico.append({"role": "assistant", "content": texto_resposta})
        salvar_memoria(sessao_id, "user", texto)
        salvar_memoria(sessao_id, "katarina", texto_resposta)
        expressao = classificar_expressao(texto_resposta)
        await avisar_overlay("fala", texto_resposta, expressao)

    return {"resposta": texto_resposta}

@app.get("/")
async def status():
    count = supabase.table("memorias").select("id", count="exact").execute()
    return {"status": "Katarina online", "memoria": count.count}
