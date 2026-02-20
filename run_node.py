"""
run_node.py — Punto de entrada para levantar un nodo completo.

Uso:
    python run_node.py                        # bootstrap local
    python run_node.py 6001 8001              # nodo que se conecta al bootstrap local
    python run_node.py 6001 8001 http://abc.ngrok.io  # conectar a bootstrap ngrok

Si tenés ngrok corriendo, pasá la URL pública como tercer argumento.
"""

import sys, threading, time, os
import storage.storage as storage_module

# ══════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════

# URL pública del bootstrap. Cambiá esto por tu URL de ngrok.
# Ejemplo: BOOTSTRAP_URL = "https://abc123.ngrok-free.app"
# Si corrés todo local, dejalo en None y usá el argumento de línea de comandos.
BOOTSTRAP_URL = "http://127.0.0.1:8000"   # ← acá va tu URL ngrok cuando la tengas

# ══════════════════════════════════════════════════════════════════

P2P_PORT     = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
API_PORT     = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
PEER_URL_ARG = sys.argv[3]      if len(sys.argv) > 3 else None

# Determinar a qué peer conectarse
if PEER_URL_ARG:
    PEER_URL = PEER_URL_ARG                    # argumento explícito
elif BOOTSTRAP_URL and P2P_PORT != 6000:
    PEER_URL = BOOTSTRAP_URL                   # bootstrap hardcodeado
elif P2P_PORT != 6000:
    PEER_URL = "http://127.0.0.1:8000"         # bootstrap local por defecto
else:
    PEER_URL = None                            # soy el bootstrap

storage_module.DATA_DIR = f"node_data_{P2P_PORT}"

from core.blockchain import Blockchain
from core.wallet import Wallet
from network.node import Node
from miner import Miner
from network.api import create_app

print(f"""
╔══════════════════════════════════════════╗
║         NODO BLOCKCHAIN                  ║
║  P2P/API → 0.0.0.0:{API_PORT:<5}              ║
║  Data    → node_data_{P2P_PORT:<5}             ║
╚══════════════════════════════════════════╝
""")

# ── 1. Blockchain ────────────────────────────────────────────────
blockchain = Blockchain(difficulty=2)

# ── 2. Nodo P2P ─────────────────────────────────────────────────
node = Node(host="0.0.0.0", port=API_PORT, blockchain=blockchain)
node.start()

# ── 3. Miner ─────────────────────────────────────────────────────
miner_key_file = f"node_data_{P2P_PORT}/miner_wallet.pem"
os.makedirs(f"node_data_{P2P_PORT}", exist_ok=True)

if os.path.exists(miner_key_file):
    miner_wallet = Wallet(key_file=miner_key_file)
    print(f"🔑 Wallet de minero cargada")
else:
    miner_wallet = Wallet()
    miner_wallet.save(miner_key_file)
    print(f"🔑 Wallet de minero nueva → {miner_key_file}")

miner = Miner(blockchain=blockchain, node=node, miner_address=miner_wallet.address())
miner.start()

# ── 4. API REST + P2P ────────────────────────────────────────────
app = create_app(blockchain, node, miner)

api_thread = threading.Thread(
    target=lambda: app.run(
        host="0.0.0.0", port=API_PORT,
        debug=False, use_reloader=False
    ),
    daemon=True, name="api"
)
api_thread.start()
time.sleep(1)  # esperar que Flask arranque

# ── 5. Conectar al peer/bootstrap ────────────────────────────────
if PEER_URL:
    print(f"\n🔗 Conectando a {PEER_URL}...")
    success = node.connect_to_peer(
        peer_host=None, peer_port=None, peer_url=PEER_URL
    )
    if success:
        print(f"✅ Conectado y sincronizando cadena...")
    else:
        print(f"⚠️  No se pudo conectar. Arrancando solo.")

print(f"""
✅  Nodo listo en http://localhost:{API_PORT}

   GET  /status          — estado del nodo
   GET  /chain           — blockchain completa
   GET  /mining/status   — estado del miner
   POST /fund            — fondear wallet (testing)
   POST /transaction     — enviar TX
   POST /balance         — consultar balance

   Endpoints P2P (para otros nodos):
   POST /p2p/handshake
   POST /p2p/block
   POST /p2p/tx
   GET  /p2p/chain
   GET  /p2p/peers

Ctrl+C para detener
""")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nDeteniendo nodo...")
    miner.stop()
    node.stop()