import os
import time
import datetime
import requests
import random
import logging
from pathlib import Path
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from groq import Groq
from supabase import create_client

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [FASE5] %(message)s")
log = logging.getLogger("fase5")

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
SUPABASE_URL  = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY", "")
VOZ_URL       = os.getenv("VOZ_URL", "http://127.0.0.1:8001/falar")
SERVIDOR_URL  = "http://localhost:8000"

# Intervalos (em minutos) — ajuste conforme preferir
INTERVALO_CHECK_PRINCIPAL  = 1     # frequência do loop principal
PAUSA_LONGA_MINUTOS        = 45    # tempo sem interação para comentar
CHECK_IN_HORAS             = 2     # frequência do "como você está?"
SAUDACAO_COOLDOWN_HORAS    = 6     # não repete saudação do mesmo período

groq_client = Groq(api_key=GROQ_API_KEY)
supabase    = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Estado interno ────────────────────────────────────────────────────────────
estado = {
    "ultima_interacao":     datetime.datetime.now(),
    "ultima_saudacao":      None,   # datetime da última saudação enviada
    "ultimo_checkin":       None,   # datetime do último "como você está?"
    "ultimo_comentario_tela": None, # datetime do último comentário de tela
    "periodo_saudado":      None,   # "manha" | "tarde" | "noite" — evita repetir
    "ja_disse_boa_noite":   False,
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def falar(texto: str):
    """Envia para voz.py sintetizar. Silencioso se voz.py offline."""
    try:
        requests.post(VOZ_URL, json={"texto": texto}, timeout=3)
        log.info(f"Falou: {texto}")
    except Exception as e:
        log.warning(f"voz.py offline: {e}")


def servidor_online() -> bool:
    try:
        r = requests.get(SERVIDOR_URL, timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def minutos_sem_interacao() -> float:
    delta = datetime.datetime.now() - estado["ultima_interacao"]
    return delta.total_seconds() / 60


def horas_desde(dt) -> float:
    if dt is None:
        return 999
    return (datetime.datetime.now() - dt).total_seconds() / 3600


def periodo_do_dia() -> str:
    hora = datetime.datetime.now().hour
    if 5 <= hora < 12:
        return "manha"
    elif 12 <= hora < 18:
        return "tarde"
    else:
        return "noite"


def buscar_contexto_tela() -> str:
    """Busca a captura de tela mais recente do Supabase."""
    try:
        result = (
            supabase.table("screen_captures")
            .select("window_title, clean_text, timestamp")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            r = result.data[0]
            return f"Janela: {r['window_title']}\n{r['clean_text'][:800]}"
        return ""
    except Exception:
        return ""


def gerar_com_llm(prompt_sistema: str, prompt_usuario: str, max_tokens: int = 120) -> str:
    """Gera uma fala personalizada via Groq."""
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user",   "content": prompt_usuario},
            ],
            max_tokens=max_tokens,
            temperature=0.85,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"Erro LLM: {e}")
        return ""


def registrar_interacao_autonoma(tipo: str, mensagem: str):
    """Salva no Supabase para histórico e aprendizado futuro."""
    try:
        supabase.table("acoes_autonomas").insert({
            "timestamp": datetime.datetime.now().isoformat(),
            "tipo":      tipo,
            "mensagem":  mensagem,
        }).execute()
    except Exception:
        pass  # tabela opcional — não trava se não existir


# ── Ações autônomas ───────────────────────────────────────────────────────────

def acao_saudacao():
    """Bom dia / boa tarde / boa noite — uma vez por período."""
    periodo = periodo_do_dia()

    # Já saudou nesse período hoje?
    if estado["periodo_saudado"] == periodo:
        return
    # Cooldown de segurança
    if horas_desde(estado["ultima_saudacao"]) < SAUDACAO_COOLDOWN_HORAS:
        return

    hora = datetime.datetime.now().hour
    dia  = datetime.datetime.now().strftime("%A")  # nome do dia em inglês — LLM entende

    saudacoes = {
        "manha": [
            "Bom dia. Vai ser produtivo hoje ou só vai fingir?",
            "Bom dia. Tô aqui se precisar.",
            "Acordou. Ótimo. Café primeiro ou eu primeiro?",
        ],
        "tarde": [
            "Boa tarde. Tá indo bem o dia?",
            "Boa tarde. Já parou pra comer alguma coisa?",
            "Boa tarde. Meio do dia. Ainda tô aqui.",
        ],
        "noite": [
            "Boa noite. Até que enfim um horário decente.",
            "Boa noite. Como foi o dia?",
            "Boa noite. Vai dormir cedo ou vai ficar aí até tarde de novo?",
        ],
    }

    texto = random.choice(saudacoes[periodo])
    falar(texto)

    estado["periodo_saudado"]  = periodo
    estado["ultima_saudacao"]  = datetime.datetime.now()
    registrar_interacao_autonoma("saudacao", texto)
    log.info(f"Saudação [{periodo}]: {texto}")


def acao_pausa_longa():
    """Lembra de pausar se ficou muito tempo sem interação."""
    minutos = minutos_sem_interacao()
    if minutos < PAUSA_LONGA_MINUTOS:
        return

    # Não repetir mais de uma vez por hora
    if horas_desde(estado.get("ultimo_aviso_pausa")) < 1.0:
        return

    hora = datetime.datetime.now().hour
    minutos_int = int(minutos)

    pausas = [
        f"Faz {minutos_int} minutos que você não fala comigo. Tá bem?",
        f"Ei. {minutos_int} minutos de silêncio. Levanta, estica, bebe água.",
        f"Você tá aí há {minutos_int} minutos sem parar. Vai descansar um pouco.",
        "Lembra que existir inclui pausas.",
    ]

    texto = random.choice(pausas)
    falar(texto)

    estado["ultimo_aviso_pausa"] = datetime.datetime.now()
    registrar_interacao_autonoma("pausa_longa", texto)
    log.info(f"Aviso de pausa ({minutos_int} min): {texto}")


def acao_checkin():
    """Pergunta como o usuário está a cada X horas."""
    if horas_desde(estado["ultimo_checkin"]) < CHECK_IN_HORAS:
        return
    # Só faz check-in se houve interação nas últimas 3h (evita perguntar pro nada)
    if minutos_sem_interacao() > 180:
        return

    checkins = [
        "Como você tá? De verdade.",
        "Ei. Tô aqui. Aconteceu alguma coisa hoje?",
        "Tudo bem por aí? Pode falar se quiser.",
        "Já faz um tempo. Tá bem?",
    ]

    texto = random.choice(checkins)
    falar(texto)

    estado["ultimo_checkin"] = datetime.datetime.now()
    registrar_interacao_autonoma("checkin", texto)
    log.info(f"Check-in: {texto}")


def acao_comentario_tela():
    """Comenta o que está na tela usando o contexto da Fase 4."""
    # Só comenta se houve interação recente (usuário está ativo)
    if minutos_sem_interacao() > 30:
        return
    # Não comenta mais de uma vez a cada 20 minutos
    if horas_desde(estado["ultimo_comentario_tela"]) < (20 / 60):
        return

    contexto = buscar_contexto_tela()
    if not contexto or len(contexto) < 50:
        return

    prompt_sistema = """
Você é a Katarina, assistente virtual pessoal com personalidade direta e levemente sarcástica.
Com base no conteúdo da tela do usuário, faça UM comentário curto e natural (máx 2 frases).
Pode ser uma observação, dica, piada leve ou simplesmente reconhecer o que ele está fazendo.
Não diga "vejo que você está" — seja natural. Não mencione que leu a tela.
Se o conteúdo for mundano demais, responda apenas: SKIP
""".strip()

    texto = gerar_com_llm(prompt_sistema, contexto, max_tokens=100)

    if not texto or texto.strip().upper() == "SKIP":
        return

    falar(texto)
    estado["ultimo_comentario_tela"] = datetime.datetime.now()
    registrar_interacao_autonoma("comentario_tela", texto)
    log.info(f"Comentário de tela: {texto}")


def acao_boa_noite():
    """Boa noite automática quando passa da meia noite."""
    hora = datetime.datetime.now().hour
    if hora == 0 and not estado["ja_disse_boa_noite"]:
        falar("Meia noite. Ainda acordado. Clássico.")
        estado["ja_disse_boa_noite"] = True
        registrar_interacao_autonoma("boa_noite", "Meia noite.")
    elif hora == 1:
        # Reset para o próximo dia
        estado["ja_disse_boa_noite"] = False


def notificar_interacao():
    """
    Chamado pelo servidor.py quando há uma mensagem do usuário.
    Atualiza o timestamp de última interação.
    """
    estado["ultima_interacao"] = datetime.datetime.now()
    # Reset do período de saudação ao acordar (novo dia)
    if estado.get("_ultimo_dia") != datetime.date.today():
        estado["periodo_saudado"] = None
        estado["_ultimo_dia"]     = datetime.date.today()


# ── Loop principal ────────────────────────────────────────────────────────────
def tick():
    """Executado a cada INTERVALO_CHECK_PRINCIPAL minutos."""
    if not servidor_online():
        log.debug("Servidor offline, aguardando...")
        return

    agora = datetime.datetime.now()
    hora  = agora.hour

    # Só age entre 6h e 23h59 (não perturba durante a madrugada)
    if hora < 6:
        return

    acao_saudacao()
    acao_pausa_longa()
    acao_comentario_tela()

    # Check-in só no horário comercial
    if 8 <= hora < 22:
        acao_checkin()

    acao_boa_noite()


def main():
    log.info("Fase 5 iniciada — loop autônomo ativo.")
    log.info(f"Pausa longa: {PAUSA_LONGA_MINUTOS} min | Check-in: {CHECK_IN_HORAS}h")

    # Aguarda o servidor subir antes de começar
    log.info("Aguardando servidor.py ficar online...")
    for _ in range(30):
        if servidor_online():
            log.info("Servidor online. Loop autônomo ativo.")
            break
        time.sleep(5)
    else:
        log.warning("Servidor não respondeu em 150s — continuando mesmo assim.")

    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(tick, "interval", minutes=INTERVALO_CHECK_PRINCIPAL)

    # Primeiro tick imediato (saudação ao ligar o PC)
    tick()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Loop autônomo encerrado.")


if __name__ == "__main__":
    main()


# ── Endpoint HTTP para receber pings do servidor.py ──────────────────────────
# Roda em thread daemon, porta 8002
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading as _threading

class _InteracaoHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        notificar_interacao()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

def _iniciar_endpoint():
    HTTPServer(("127.0.0.1", 8002), _InteracaoHandler).serve_forever()

_threading.Thread(target=_iniciar_endpoint, daemon=True).start()