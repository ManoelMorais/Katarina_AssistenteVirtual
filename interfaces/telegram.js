const TelegramBot = require('node-telegram-bot-api')
const axios = require('axios')

// ─── Config ──────────────────────────────────────────────────────
const TELEGRAM_TOKEN = '8136697218:AAFtbWwm2LTkNr-PmRi3zwXIQP5Al6kG8hY'  // token do BotFather
const SERVIDOR_URL = 'https://katarinaassistentevirtual-production.up.railway.app/conversar'

// ─── Aguarda servidor subir ──────────────────────────────────────
async function aguardarServidor(tentativas = 10, intervalo = 3000) {
  for (let i = 0; i < tentativas; i++) {
    try {
      await axios.get('http://localhost:8000/')
      console.log('✓ Servidor online')
      return true
    } catch {
      console.log(`Aguardando servidor... (${i + 1}/${tentativas})`)
      await new Promise(r => setTimeout(r, intervalo))
    }
  }
  console.log('Servidor não respondeu. Continuando mesmo assim...')
  return false
}

const bot = new TelegramBot(TELEGRAM_TOKEN, { polling: true })
console.log('✓ Katarina conectada no Telegram')

bot.on('message', async (msg) => {
  const chatId = msg.chat.id.toString()
  const texto  = msg.text
  if (!texto || !texto.trim()) return
  console.log(`Você: ${texto}`)
  try {
    bot.sendChatAction(chatId, 'typing')
    const { data } = await axios.post(SERVIDOR_URL, {
      sessao_id: chatId,
      texto: texto
    })
    console.log(`Katarina: ${data.resposta}`)
    bot.sendMessage(chatId, data.resposta)
  } catch (erro) {
    console.error('Erro:', erro.message)
    bot.sendMessage(chatId, 'Problema técnico, tenta de novo.')
  }
})

bot.on('polling_error', (erro) => {
  console.error('Erro de conexão:', erro.message)
})

// ─── Inicia aguardando o servidor ────────────────────────────────
aguardarServidor()