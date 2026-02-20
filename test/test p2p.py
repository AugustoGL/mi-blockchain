"""
test_p2p.py — Prueba la red P2P con dos nodos en la misma máquina.
"""

import time
import shutil
import os

# Parchamos storage ANTES de importar Blockchain
import storage.storage as storage_module

def make_blockchain(data_dir):
    original_dir            = storage_module.DATA_DIR
    storage_module.DATA_DIR = data_dir
    from core.blockchain import Blockchain
    bc = Blockchain(difficulty=3)
    storage_module.DATA_DIR = original_dir
    return bc

from core.wallet import Wallet
from network.node import Node

# Limpiamos datos previos
for folder in ["data_nodo_a", "data_nodo_b", "data_nodo_c"]:
    if os.path.exists(folder):
        shutil.rmtree(folder)

print("\n" + "="*50)
print("🌐 TEST RED P2P — 3 nodos")
print("="*50 + "\n")

# ── Crear blockchains ──
bc_a = make_blockchain("data_nodo_a")
bc_b = make_blockchain("data_nodo_b")

# ── Crear y arrancar nodos ──
nodo_a = Node("127.0.0.1", 6000, bc_a)
nodo_b = Node("127.0.0.1", 6001, bc_b)
nodo_a.start()
nodo_b.start()
time.sleep(0.3)

# ── TEST 1: Conexión ──
print("── TEST 1: Conexión entre nodos ──")
nodo_b.connect_to_peer("127.0.0.1", 6000)
time.sleep(0.5)

assert len(nodo_a.peers) >= 1
assert len(nodo_b.peers) >= 1
print("✅ Nodos conectados")

# ── TEST 2: Propagar TX ──
print("\n── TEST 2: Propagación de transacción ──")
alice = Wallet()
bob   = Wallet()
alice.fund_initial_balance(bc_a, amount=50)

tx = alice.create_transaction(bc_a, bob.address(), 10, 1)
result = nodo_a.announce_transaction(tx)
assert result is True
time.sleep(0.5)
print("✅ TX anunciada a la red")

# ── TEST 3: Propagar bloque ──
print("\n── TEST 3: Propagación de bloque ──")
miner_a = Wallet()
miner_a.fund_initial_balance(bc_a, amount=50)
bc_a.mine_pending_transactions(miner_a.address())
bloque = bc_a.get_latest_block()
print(f"Nodo A minó bloque #{bloque.index}")

nodo_a.announce_block(bloque)
time.sleep(0.8)
print(f"Cadena A: {len(bc_a.chain)} bloques | Cadena B: {len(bc_b.chain)} bloques")
print("✅ Bloque anunciado a la red")

# ── TEST 4: Nodo nuevo se sincroniza ──
print("\n── TEST 4: Sincronización de nodo nuevo ──")
bc_c  = make_blockchain("data_nodo_c")
nodo_c = Node("127.0.0.1", 6002, bc_c)
nodo_c.start()
time.sleep(0.3)

# Al conectarse manda PEDIR_CADENA automáticamente
nodo_c.connect_to_peer("127.0.0.1", 6000)
time.sleep(1.5)

print(f"Cadena A: {len(bc_a.chain)} bloques | Cadena C (recién unido): {len(bc_c.chain)} bloques")
print("✅ Sincronización funcionando")

# ── TEST 5: Status ──
print("\n── Estado final de los nodos ──")
for nombre, nodo in [("A", nodo_a), ("B", nodo_b), ("C", nodo_c)]:
    s = nodo.get_status()
    print(f"  Nodo {nombre}: puerto={s['port']} | peers={s['peers']} | bloques={s['chain_length']} | utxos={s['utxos']}")

nodo_a.stop()
nodo_b.stop()
nodo_c.stop()

for folder in ["data_nodo_a", "data_nodo_b", "data_nodo_c"]:
    if os.path.exists(folder):
        shutil.rmtree(folder)

print("\n🎉 RED P2P FUNCIONANDO")