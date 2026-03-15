# Katarina

IA pessoal com personalidade, memória e presença visual.

## Estrutura

```
Katarina/
├── core/
│   ├── servidor.py     — API FastAPI (cérebro)
│   ├── katarina.py     — terminal fallback
│   └── perfil.md       — quem é o Manoel
├── interfaces/
│   ├── telegram.js     — bot Telegram
│   └── package.json
├── overlay/
│   ├── overlay.js      — Electron
│   ├── overlay.html    — avatar + animações
│   ├── package.json
│   └── assets/         — GIFs e PNGs da Katarina
├── memoria/            — ChromaDB local (não editar)
├── config/
│   └── config.py       — TODAS as configurações aqui
└── iniciar.bat         — abre tudo com 1 clique
```

## Como rodar

Duplo clique no `iniciar.bat`.

Ou manualmente, em 3 terminais:

```bash
# Terminal 1 — servidor
cd core
python -m uvicorn servidor:app --host 0.0.0.0 --port 8000

# Terminal 2 — overlay
cd overlay
npx electron .

# Terminal 3 — Telegram
cd interfaces
node telegram.js
```

## Configuração

Edite `config/config.py`:
- `GROQ_API_KEY` — sua chave do Groq
- `TEMPO_PROATIVO_MINUTOS` — frequência das aparições espontâneas
- `MAX_TOKENS` — tamanho máximo das respostas

Edite `interfaces/telegram.js` linha 5:
- `TELEGRAM_TOKEN` — token do BotFather

## Atalhos

- `Ctrl+Shift+K` — mostra/esconde o overlay

## Fases concluídas

- [x] Fase 1 — Cérebro + personalidade
- [x] Fase 2 — Memória vetorial
- [x] Fase 2.5 — Interface Telegram
- [x] Fase 3 — Overlay animado

## Próximas fases

- [ ] Fase 4 — Voz (wake word + TTS)
- [ ] Fase 5 — Leitura de tela + loop autônomo
- [ ] Deploy Railway — 24h online
