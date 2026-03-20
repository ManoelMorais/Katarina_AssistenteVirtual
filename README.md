# Katarina — Assistente Virtual Pessoal

> Assistente virtual local, com voz, memória, presença visual e autonomia. Roda no seu PC com Windows, sem depender de plataformas de terceiros.

---

## O que é

A Katarina é uma assistente pessoal construída para ser uma presença real — não um chatbot que responde perguntas. Ela ouve por voz, aparece na tela com um avatar pixel art, lembra de conversas anteriores, lê o que está acontecendo na sua tela, e age por conta própria com base em horário e contexto.

A ideia original: ter algo com quem conversar de verdade — contar o que está acontecendo, pensar em voz alta, e ter do outro lado alguém que entende o contexto e lembra do que foi dito antes.

---

## Funcionalidades

### Voz
- Wake word **"Assistente"** detectada localmente via Porcupine
- Transcrição de fala via **Groq Whisper** (< 1 segundo)
- Síntese de voz via **edge_tts** (FranciscaNeural)
- Captura dinâmica com VAD — para automaticamente no silêncio
- Comando de voz: **"Assistente, para"** pausa tudo / **"Assistente, voltar"** retoma

### Visual
- Overlay transparente sobre a tela (Electron)
- Avatar pixel art com **8 expressões**: neutra, falando, séria, feliz, brava, irônica, surpresa, pensativa
- Balão de texto com animação de entrada/saída
- Gestos idle aleatórios quando inativa
- **Ctrl+Shift+K** pausa/retoma visualmente

### Memória
- Histórico de conversas salvo no **Supabase** com embedding vetorial
- Busca semântica nas memórias relevantes a cada mensagem
- Resumo automático de sessão

### Leitura de tela (Fase 4)
- Captura periódica + gatilho por mudança de janela
- OCR local via **pytesseract**
- Análise via LLM — decide se comenta, alerta ou fica em silêncio
- Cooldown de 5 minutos entre comentários
- Contexto de tela injetado silenciosamente no system prompt

### Loop autônomo (Fase 5)
- Saudações por período do dia (bom dia / boa tarde / boa noite)
- Lembrete de pausa após 45 minutos sem interação
- Check-in "como você está?" a cada 2 horas
- Comentários contextuais sobre o que está na tela
- Silêncio automático entre 0h e 6h

### Interfaces
- **Voz** (processo principal)
- **Telegram** (bot para acesso remoto)
- **FastAPI** (servidor HTTP na porta 8000)

---

## Estrutura do projeto

```
katarina/
├── core/
│   ├── servidor.py          # FastAPI — LLM, memória, Fase 4
│   ├── voz.py               # Wake word, gravação, TTS, servidor :8001
│   ├── loop_autonomo.py     # Ações autônomas, scheduler, servidor :8002
│   ├── screen_reader.py     # Captura de tela, OCR, análise
│   ├── screen_context.py    # Estado compartilhado da tela
│   ├── estado_global.py     # Flag de pausa e estado central
│   └── perfil.md            # Personalidade e perfil do usuário
├── overlay/
│   ├── overlay.html         # Interface visual (Electron renderer)
│   ├── overlay.js           # Processo principal Electron, servidor :3000
│   └── assets/              # GIFs e PNGs do avatar
├── interfaces/
│   └── telegram.js          # Bot Telegram
├── config/
│   └── config.py
├── launcher/                # Scripts VBS para inicialização invisível
│   ├── run_servidor.vbs
│   ├── run_overlay.vbs
│   ├── run_telegram.vbs
│   ├── run_voz.vbs
│   └── run_loop.vbs
├── iniciar.bat              # Sobe todos os processos
├── autostart.vbs            # Coloca na inicialização do Windows
├── main.py
├── perfil.md
└── requirements.txt
```

---

## Arquitetura

Cinco processos independentes comunicando via HTTP local:

```
iniciar.bat
├── servidor.py     :8000  — LLM + memória + screen reader
├── voz.py          :8001  — wake word + TTS + pause/resume
├── loop_autonomo   :8002  — ações autônomas + scheduler
├── overlay         :3000  — visual + expressões
└── telegram.js     —      — interface Telegram
```

**Fluxo de uma conversa por voz:**
```
wake word detectada
  → gravar_audio() com VAD
  → Groq Whisper (transcrição)
  → POST :8000/conversar
      → busca memórias relevantes (Supabase)
      → injeta contexto de tela (screen_context)
      → LLM gera resposta (Groq llama-3.3-70b)
  → edge_tts sintetiza áudio
  → POST :3000 (overlay anima)
  → playsound toca
```

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| LLM | Groq — llama-3.3-70b-versatile |
| Transcrição | Groq Whisper large-v3-turbo |
| Memória | Supabase + pgvector |
| Voz síntese | edge_tts (pt-BR-FranciscaNeural) |
| Wake word | Porcupine (Picovoice) |
| Visual | Electron + HTML/CSS/JS |
| OCR | pytesseract + mss |
| API | FastAPI + uvicorn |
| Scheduler | APScheduler |
| Deploy | Railway (servidor) + Supabase (memória) |

---

## Instalação

### Requisitos

- Python 3.10+
- Node.js 18+
- Windows 10/11
- Tesseract OCR instalado no sistema

### Tesseract (obrigatório para Fase 4)

Baixe em: https://github.com/UB-Mannheim/tesseract/wiki

Durante a instalação marque: **Portuguese** e **English**

Adicione ao PATH: `C:\Program Files\Tesseract-OCR`

### Dependências Python

```bash
pip install -r requirements.txt
```

### Dependências Node

```bash
cd overlay && npm install
cd interfaces && npm install
```

### Variáveis de ambiente

Crie um arquivo `.env` na raiz:

```env
GROQ_API_KEY=
PICOVOICE_KEY=
SUPABASE_URL=
SUPABASE_KEY=
ELEVENLABS_API_KEY=
SYSTEM_PROMPT=
OVERLAY_URL=http://127.0.0.1:3000
VOZ_URL=http://127.0.0.1:8001/falar
TEMPO_PROATIVO_MINUTOS=5
MAX_TOKENS=80
TEMPERATURE=0.85
```

### Banco de dados (Supabase)

Execute em ordem no SQL Editor do Supabase:

1. Migration de memórias (existente)
2. `fase4_migration.sql` — tabela `screen_captures`
3. `fase5_migration.sql` — tabela `acoes_autonomas`

---

## Como iniciar

### Manual
```bash
iniciar.bat
```

### Automático com o Windows

1. Edite `autostart.vbs` com o caminho real do projeto
2. Pressione `Win + R`, digite `shell:startup`, Enter
3. Cole o `autostart.vbs` na pasta que abrir

Na próxima vez que logar no Windows, a Katarina sobe sozinha em background.

---

## Comandos de voz

| Fala | Ação |
|------|------|
| `"Assistente"` | Ativa o modo de conversa |
| `"Assistente, para"` | Pausa tudo |
| `"Assistente, voltar"` | Retoma após pausa |
| `"Ligar assistente"` | Modo contínuo (sem precisar da wake word) |
| `"O que você vê?"` | Descreve o conteúdo da tela |

## Atalhos

| Atalho | Ação |
|--------|------|
| `Ctrl+Shift+K` | Pausa/retoma toda a Katarina |

---

## Portas locais

| Porta | Processo | Uso |
|-------|----------|-----|
| `:8000` | servidor.py | API principal — `/conversar`, `/` |
| `:8001` | voz.py | TTS — `POST /falar`, `POST /pausar` |
| `:8002` | loop_autonomo.py | Interação — `POST /interacao` |
| `:3000` | overlay (Electron) | Eventos visuais — `POST /` |

---

## Status das fases

- ✅ Fase 1 — LLM + personalidade
- ✅ Fase 2 — Memória vetorial
- ✅ Fase 2.5 — Interfaces (Terminal, Telegram, FastAPI)
- ✅ Fase 3 — Overlay + voz + wake word + sincronização
- ✅ Fase 4 — Leitura de tela com OCR
- ✅ Fase 5 — Loop autônomo + autostart
- 🔄 Próximo — sincronia overlay/voz, estado emocional, evolução com tempo

---

## Problemas conhecidos

- Expressão do overlay cobre poucos casos — maioria cai em "falando"
- Overlay anima antes do áudio começar (delay de síntese TTS)
- Loop autônomo baseado em tempo, não em contexto
- Evolução com o tempo depende de job de análise de padrões ainda não implementado

---

## Licença

Projeto pessoal. Uso livre.