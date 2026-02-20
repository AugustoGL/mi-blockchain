"""
test_transferencias.py
======================
Crea wallets, las fondea via API y hace transferencias entre nodos.

Uso:
    python test_transferencias.py

Requiere que los nodos estén corriendo.
"""

import sys, os, json, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Configuración ─────────────────────────────────────────────────
NODOS = [
    {"nombre": "A", "api": 8000},
    {"nombre": "B", "api": 8001},
    {"nombre": "C", "api": 8002},
    {"nombre": "D", "api": 8003},
    {"nombre": "E", "api": 8004},
]

# ── HTTP helpers ──────────────────────────────────────────────────

def get(port, path):
    res = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5)
    return json.loads(res.read())

def post(port, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        res = urllib.request.urlopen(req, timeout=5)
        return json.loads(res.read()), res.getcode()
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code

# ── Verificar nodos vivos ─────────────────────────────────────────

print("\n" + "="*55)
print("🔍  VERIFICANDO NODOS")
print("="*55)

nodos_vivos = []
for n in NODOS:
    try:
        r = get(n["api"], "/status")
        chain = r["data"]["chain_length"]
        peers = len(r["data"]["peers"])
        print(f"  ✅ Nodo {n['nombre']} (:{n['api']}) — {chain} bloques, {peers} peers")
        nodos_vivos.append(n)
    except:
        print(f"  ❌ Nodo {n['nombre']} (:{n['api']}) — no disponible")

if not nodos_vivos:
    print("\n❌ Ningún nodo disponible.")
    sys.exit(1)

nodo_ref = nodos_vivos[0]
print(f"\n  Nodo de referencia: {nodo_ref['nombre']} (puerto {nodo_ref['api']})")

# ── Crear wallets ─────────────────────────────────────────────────

print("\n" + "="*55)
print("👛  CREANDO WALLETS")
print("="*55)

from core.wallet import Wallet

alice = Wallet()
bob   = Wallet()
carol = Wallet()
dave  = Wallet()
eva   = Wallet()

usuarios = [("Alice", alice), ("Bob", bob), ("Carol", carol), ("Dave", dave), ("Eva", eva)]
for nombre, w in usuarios:
    print(f"  {nombre}: {w.address().decode().strip().splitlines()[1][:30]}...")

# ── Fondear via API /fund ─────────────────────────────────────────
# Esto llama al endpoint del nodo — los fondos quedan en su UTXO set real

print("\n" + "="*55)
print("💰  FONDEANDO WALLETS VIA API")
print("="*55)

fondos = [("Alice", alice, 1000), ("Bob", bob, 500), ("Carol", carol, 300),
          ("Dave", dave, 200), ("Eva", eva, 150)]

for nombre, wallet, monto in fondos:
    r, code = post(nodo_ref["api"], "/fund", {
        "address": wallet.address().decode(),
        "amount": monto
    })
    if r["ok"]:
        print(f"  ✅ {nombre}: {monto} coins fondeados")
    else:
        print(f"  ❌ {nombre}: {r.get('error')}")

# Esperar que se mine el bloque con los fondos
print("\n⏳ Esperando que un miner incluya los fondos...")
chain_inicial = get(nodo_ref["api"], "/status")["data"]["chain_length"]
for _ in range(30):
    time.sleep(1)
    chain_actual = get(nodo_ref["api"], "/status")["data"]["chain_length"]
    if chain_actual > chain_inicial:
        print(f"  ✅ Bloque #{chain_actual} minado")
        break
else:
    print("  ⚠️  Sin nuevo bloque aún, continuando...")

# ── Helpers de TX ─────────────────────────────────────────────────

def balance(wallet):
    r, _ = post(nodo_ref["api"], "/balance", {"address": wallet.address().decode()})
    return r["data"]["balance"] if r["ok"] else 0

def ver_balances(titulo="Balances"):
    print(f"\n  ── {titulo} ──")
    for nombre, wallet in usuarios:
        print(f"    {nombre:6s}: {balance(wallet):>6} coins")

def ver_red(titulo="Estado de la red"):
    print(f"\n  ── {titulo} ──")
    for n in nodos_vivos:
        r = get(n["api"], "/status")["data"]
        print(f"    Nodo {n['nombre']}: {r['chain_length']} bloques │ "
              f"{r['pending_txs']} pendientes │ {r['utxo_count']} UTXOs")

def transferir(wallet_origen, nombre_origen, api_port, nombre_nodo,
               wallet_receptor, nombre_receptor, monto, fee=2):
    """
    Crea la TX localmente usando el UTXO set del nodo y la manda via API.
    Para tener el UTXO set actualizado, primero lo descarga del nodo.
    """
    # Descargar UTXOs del emisor desde el nodo
    r, _ = post(api_port, "/balance", {"address": wallet_origen.address().decode()})
    if not r["ok"] or r["data"]["balance"] < monto + fee:
        bal = r["data"]["balance"] if r["ok"] else 0
        print(f"  ❌ {nombre_origen} → {nombre_receptor:<8} "
              f"{monto:>5} coins │ fondos insuficientes (tiene {bal})")
        return False

    # Reconstruir un blockchain mínimo con los UTXOs del nodo
    from core.blockchain import Blockchain
    import storage.storage as storage_module

    # Usar el data_dir del nodo de referencia para cargar la cadena real
    data_dir_orig = storage_module.DATA_DIR

    # Encontrar el data_dir del nodo al que le mandamos la TX
    nodo_target = next((n for n in nodos_vivos if n["api"] == api_port), nodo_ref)
    # Inferir data_dir desde el puerto P2P (api_port - 2000 + 6000)
    p2p_port = api_port - 2000
    storage_module.DATA_DIR = f"node_data_{p2p_port}"

    try:
        bc = Blockchain.__new__(Blockchain)
        bc.difficulty = 2
        bc.pending_transactions = []
        bc._locked_utxos = set()

        # Cargar UTXOs desde la API en vez del disco
        utxos_r = get(api_port, "/utxos")["data"]["utxos"]
        from core.transaction import TxOutput
        bc.utxo_set = {}
        for u in utxos_r:
            pk = u["owner"].encode() if isinstance(u["owner"], str) else u["owner"]
            bc.utxo_set[(u["tx_id"], u["index"])] = TxOutput(
                amount=u["amount"],
                recipient_public_key_pem=pk
            )

        tx = wallet_origen.create_transaction(
            bc,
            wallet_receptor.address(),
            monto,
            fee
        )
    except Exception as e:
        print(f"  ❌ {nombre_origen} → {nombre_receptor:<8} "
              f"{monto:>5} coins │ Error creando TX: {e}")
        storage_module.DATA_DIR = data_dir_orig
        return False
    finally:
        storage_module.DATA_DIR = data_dir_orig

    r, code = post(api_port, "/transaction", tx.to_dict())
    if r["ok"]:
        tx_id = r["data"]["tx_id"][:12]
        print(f"  ✅ {nombre_origen} → {nombre_receptor:<8} "
              f"{monto:>5} coins │ [nodo {nombre_nodo}] TX:{tx_id}...")
        return True
    else:
        print(f"  ❌ {nombre_origen} → {nombre_receptor:<8} "
              f"{monto:>5} coins │ {r.get('error','?')}")
        return False

def esperar_minado(segundos=15):
    print(f"\n⏳ Esperando minado (máx {segundos}s)...")
    chain_antes = get(nodo_ref["api"], "/status")["data"]["chain_length"]
    for i in range(segundos):
        time.sleep(1)
        pendientes = get(nodo_ref["api"], "/status")["data"]["pending_txs"]
        chain_ahora = get(nodo_ref["api"], "/status")["data"]["chain_length"]
        if pendientes == 0 and chain_ahora > chain_antes:
            print(f"  ✅ Minado en {i+1}s (bloque #{chain_ahora})")
            return
    print("  ⚠️  Tiempo agotado, puede que aún esté minando")

# ── Estado inicial ─────────────────────────────────────────────────
ver_balances("Balances iniciales")
ver_red("Estado inicial")

# ── Ronda 1 ───────────────────────────────────────────────────────
print("\n" + "="*55)
print("📤  RONDA 1 — Transferencias iniciales")
print("="*55)

api0 = nodos_vivos[0]["api"]
api1 = nodos_vivos[min(1, len(nodos_vivos)-1)]["api"]
api2 = nodos_vivos[min(2, len(nodos_vivos)-1)]["api"]

transferir(alice, "Alice", api0, nodos_vivos[0]["nombre"], bob,   "Bob",   100)
transferir(alice, "Alice", api0, nodos_vivos[0]["nombre"], carol, "Carol",  80)
transferir(bob,   "Bob",   api1, nodos_vivos[min(1,len(nodos_vivos)-1)]["nombre"], dave,  "Dave",   50)
transferir(carol, "Carol", api1, nodos_vivos[min(1,len(nodos_vivos)-1)]["nombre"], eva,   "Eva",    40)

esperar_minado()
ver_balances("Balances tras ronda 1")

# ── Ronda 2 ───────────────────────────────────────────────────────
print("\n" + "="*55)
print("📤  RONDA 2 — Transferencias cruzadas")
print("="*55)

transferir(bob,   "Bob",   api0, nodos_vivos[0]["nombre"],                          alice, "Alice",  30)
transferir(dave,  "Dave",  api2, nodos_vivos[min(2,len(nodos_vivos)-1)]["nombre"],  carol, "Carol",  15)
transferir(eva,   "Eva",   api1, nodos_vivos[min(1,len(nodos_vivos)-1)]["nombre"],  bob,   "Bob",    10)

esperar_minado()
ver_balances("Balances tras ronda 2")

# ── Ronda 3 ───────────────────────────────────────────────────────
print("\n" + "="*55)
print("📤  RONDA 3 — Cadena de pagos")
print("="*55)

transferir(alice, "Alice", api0, nodos_vivos[0]["nombre"], bob,   "Bob",   50)
transferir(bob,   "Bob",   api0, nodos_vivos[0]["nombre"], carol, "Carol", 30)
transferir(carol, "Carol", api0, nodos_vivos[0]["nombre"], dave,  "Dave",  20)
transferir(dave,  "Dave",  api0, nodos_vivos[0]["nombre"], eva,   "Eva",   10)

esperar_minado()

# ── Resumen ───────────────────────────────────────────────────────
print("\n" + "="*55)
print("📊  RESUMEN FINAL")
print("="*55)

ver_red("Estado final")
ver_balances("Balances finales")

chain_len = get(nodo_ref["api"], "/status")["data"]["chain_length"]
print(f"\n  ── Últimos 3 bloques ──")
for idx in range(max(0, chain_len - 3), chain_len):
    r = get(nodo_ref["api"], f"/block/{idx}")["data"]
    print(f"    #{r['index']}  {len(r['transactions'])} TXs  "
          f"nonce={r['nonce']}  {r['hash'][:20]}...")

print("\n✅  TEST COMPLETADO")