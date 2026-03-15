const { app, BrowserWindow, ipcMain, screen, globalShortcut } = require('electron')
const http = require('http')

let overlayWindow = null
let visivel = true

function criarOverlay() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize

  overlayWindow = new BrowserWindow({
    width: width,
    height: height,
    x: 0,
    y: 0,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    focusable: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  })

  overlayWindow.loadFile('overlay.html')
  overlayWindow.setIgnoreMouseEvents(true)
}

function iniciarServidor() {
  const server = http.createServer((req, res) => {
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS')
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type')

    if (req.method === 'OPTIONS') {
      res.writeHead(200)
      res.end()
      return
    }

    if (req.method === 'POST') {
      let body = ''
      req.on('data', chunk => { body += chunk })
      req.on('end', () => {
        try {
          const data = JSON.parse(body)
          if (overlayWindow && !overlayWindow.isDestroyed()) {
            if (data.evento === 'fala') {
              overlayWindow.webContents.send('katarina-fala', {
                texto: data.texto,
                expressao: data.expressao || 'falando'
              })
            } else if (data.evento === 'ouve') {
              overlayWindow.webContents.send('katarina-ouve')
            } else if (data.evento === 'idle') {
              overlayWindow.webContents.send('katarina-idle')
            }
          }
          res.writeHead(200)
          res.end(JSON.stringify({ ok: true }))
        } catch (e) {
          res.writeHead(400)
          res.end(JSON.stringify({ erro: e.message }))
        }
      })
    }
  })

  server.listen(3000, '127.0.0.1', () => {
    console.log('✓ Overlay ouvindo na porta 3000')
  })
}

app.whenReady().then(() => {
  criarOverlay()
  iniciarServidor()

  // Ctrl+Shift+K — mostra/esconde
  globalShortcut.register('CommandOrControl+Shift+K', () => {
    if (!overlayWindow) return
    visivel = !visivel
    visivel ? overlayWindow.show() : overlayWindow.hide()
  })

  console.log('✓ Katarina overlay ativo')
})

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
})

app.on('window-all-closed', () => {
  app.quit()
})