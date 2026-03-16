from fastapi import FastAPI
from pydantic import BaseModel
from groq import Groq
from supabase import create_client
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import os, sys, datetime, httpx, random, hashlib, asyncio, numpy as np

# ── Fase 4 — imports ──────────────────────────────────────────────────────────
from screen_context import screen_ctx
from screen_reader import ScreenReader, is_screen_question, answer_about_screen

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODELO = "llama-3.3-70b-versatile"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 80))
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.85))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OVERLAY_URL = os.getenv("OVERLAY_URL", "http://127.0.0.1:3000")
TEMPO_PROATIVO_MINUTOS = int(os.getenv("TEMPO_PROATIVO_MINUTOS", 5))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PERFIL_PATH = os.path.join(BASE_DIR, "perfil.md")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY não encontrada no ambiente/.env")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL/SUPABASE_KEY não encontradas no ambiente/.env")

app = FastAPI()

groq_client = Groq(api_key=GROQ_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
scheduler = AsyncIOScheduler()
historicos = {}


# ─── Perfil ───────────────────────────────────────────────────────────────────
def carregar_perfil():
    perfil = os.getenv("PERFIL_CONTEUDO")
    if perfil:
        return perfil
    try:
        with open(PERFIL_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "Perfil não encontrado."


perfil = carregar_perfil()


# ─── Embedding leve (sem pytorch) ────────────────────────────────────────────
def gerar_embedding(texto: str) -> list:
    tokens = texto.lower().split()
    vec = np.zeros(384)
    for i, token in enumerate(tokens[:384]):
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        idx = h % 384
        vec[idx] += 1.0 / (i + 1)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


# ─── Memória ──────────────────────────────────────────────────────────────────
def salvar_memoria(sessao_id: str, role: str, texto: str):
    try:
        embedding = gerar_embedding(texto)
        supabase.table("memorias").insert(
            {
                "sessao_id": sessao_id,
                "role": role,
                "texto": f"[{role.upper()}] {texto}",
                "embedding": embedding,
                "timestamp": datetime.datetime.now().isoformat(),
            }
        ).execute()
    except Exception as e:
        print(f"Erro ao salvar memória: {e}")


def buscar_memorias(sessao_id: str, texto: str, n: int = 5) -> str:
    try:
        embedding = gerar_embedding(texto)
        result = supabase.rpc(
            "buscar_memorias",
            {
                "query_embedding": embedding,
                "match_count": n,
                "sessao_filter": sessao_id,
            },
        ).execute()
        if result.data:
            return "\n".join([r["texto"] for r in result.data])
        return ""
    except Exception:
        return ""


# ─── Expressão ────────────────────────────────────────────────────────────────
def classificar_expressao(texto: str) -> str:
    t = texto.lower()
    if any(p in t for p in ["sério isso", "lá vem você", "kk", "kkk"]):
        return "ironica"
    if any(p in t for p in ["ótimo", "feliz", "massa", "show"]):
        return "feliz"
    if any(p in t for p in ["errado", "problema", "cuidado"]):
        return "brava"
    if any(p in t for p in ["como assim", "espera", "nossa"]):
        return "surpresa"
    if any(p in t for p in ["talvez", "não sei", "difícil"]):
        return "pensativa"
    if any(p in t for p in ["entendo", "tô aqui", "ouço"]):
        return "seria"
    return "falando"


# ─── Overlay ──────────────────────────────────────────────────────────────────
async def avisar_overlay(evento: str, texto: str = "", expressao: str = "falando"):
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            await client.post(
                OVERLAY_URL,
                json={"evento": evento, "texto": texto, "expressao": expressao},
            )
    except Exception:
        pass


# ─── System prompt base ───────────────────────────────────────────────────────
system_prompt_base = f"{SYSTEM_PROMPT}\n\nO perfil dele:\n---\n{perfil}\n---"


# ── Fase 4 — monta system prompt com contexto de tela ────────────────────────
def build_system_prompt() -> str:
    """
    Injeta o contexto atual da tela no system prompt silenciosamente.
    Se não houver captura ainda, retorna o prompt base sem alteração.
    """
    snippet = screen_ctx.to_prompt_snippet()
    if snippet:
        return f"{system_prompt_base}\n\n{snippet}"
    return system_prompt_base


# ─── Proativo ─────────────────────────────────────────────────────────────────
msgs_proativas = [
    ("Ei, tô aqui. Sumiu.", "ironica"),
    ("Tô te observando.", "seria"),
    ("Oi. Só passando.", "feliz"),
    ("Ainda vivo aí?", "ironica"),
    ("Lembrei de você.", "neutra"),
    ("Tá bem?", "seria"),
]


async def aparicao_proativa():
    texto, expressao = random.choice(msgs_proativas)
    await avisar_overlay("fala", texto, expressao)


# ─── Startup ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    # Proativo existente
    scheduler.add_job(aparicao_proativa, "interval", minutes=TEMPO_PROATIVO_MINUTOS)
    scheduler.start()

    # ── Fase 4 — callbacks de voz da Katarina ────────────────────────────────
    async def falar_overlay(texto: str):
        """Callback usado pelo ScreenReader para comentários e alertas por voz."""
        expressao = classificar_expressao(texto)
        await avisar_overlay("fala", texto, expressao)

    def falar_sync(texto: str):
        """Wrapper síncrono para o asyncio.create_task funcionar no callback."""
        asyncio.create_task(falar_overlay(texto))

    # Sobe o ScreenReader como task paralela — não bloqueia o servidor
    reader = ScreenReader(
        groq_client=groq_client,
        supabase=supabase,
        screen_context=screen_ctx,
        on_alert=falar_sync,  # alerta fala com prioridade
        on_comment=falar_sync,  # comentário proativo
        monitor_index=1,  # monitor principal
        lang="por+eng",  # Português + Inglês
    )
    asyncio.create_task(reader.start())


# ─── Endpoints ────────────────────────────────────────────────────────────────
class Mensagem(BaseModel):
    sessao_id: str
    texto: str


@app.post("/conversar")
async def conversar(msg: Mensagem):
    sessao_id = msg.sessao_id
    texto = msg.texto

    await avisar_overlay("ouve")

    # ── Fase 4 — resposta sob demanda sobre a tela ───────────────────────────
    if is_screen_question(texto):
        loop = asyncio.get_event_loop()
        texto_resposta = await loop.run_in_executor(
            None, answer_about_screen, texto, screen_ctx, groq_client
        )
        expressao = classificar_expressao(texto_resposta)
        await avisar_overlay("fala", texto_resposta, expressao)
        return {"resposta": texto_resposta}

    # ── Fluxo normal ─────────────────────────────────────────────────────────
    if sessao_id not in historicos:
        # Fase 4 — usa build_system_prompt() em vez de system_prompt direto
        historicos[sessao_id] = [{"role": "system", "content": build_system_prompt()}]

    historico = historicos[sessao_id]

    # Fase 4 — atualiza o system prompt com o contexto de tela mais recente
    if historico and historico[0]["role"] == "system":
        historico[0]["content"] = build_system_prompt()

    memorias = buscar_memorias(sessao_id, texto)
    hist_mem = list(historico)

    if memorias:
        hist_mem.append(
            {"role": "system", "content": f"Memórias relevantes:\n{memorias}"}
        )

    hist_mem.append({"role": "user", "content": texto})

    resposta = groq_client.chat.completions.create(
        model=MODELO, messages=hist_mem, max_tokens=MAX_TOKENS, temperature=TEMPERATURE
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
    try:
        count = supabase.table("memorias").select("id", count="exact").execute()
        return {
            "status": "Katarina online",
            "memoria": count.count,
            # Fase 4 — info de contexto de tela no status
            "tela_ativa": screen_ctx.current_window or "sem captura",
            "tela_atualizada": (
                screen_ctx.last_update.isoformat() if screen_ctx.last_update else None
            ),
        }
    except Exception:
        return {"status": "Katarina online"}
