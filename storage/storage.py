"""
storage.py — Persistencia de la blockchain en disco.

Guarda y carga tres archivos JSON:
  - chain.json     → la cadena de bloques completa
  - utxo_set.json  → el conjunto de UTXOs (monedas no gastadas)
  - mempool.json   → transacciones pendientes de minar
"""

import json
import os


# Carpeta donde se guardan los archivos. Se crea sola si no existe.
DATA_DIR = "blockchain_data"


def _ensure_dir():
    """Crea la carpeta de datos si todavía no existe."""
    os.makedirs(DATA_DIR, exist_ok=True)


def _path(filename):
    """Devuelve la ruta completa a un archivo dentro de DATA_DIR."""
    return os.path.join(DATA_DIR, filename)


# ==============================================================================
# GUARDAR
# ==============================================================================

def save_chain(chain):
    """
    Serializa la lista de bloques a JSON y la guarda en chain.json.
    Cada bloque se convierte con su propio to_dict().
    """
    _ensure_dir()
    data = [block.to_dict() for block in chain]

    with open(_path("chain.json"), "w") as f:
        json.dump(data, f, indent=2)

    print(f"💾 Cadena guardada ({len(chain)} bloques)")


def save_utxo_set(utxo_set):
    """
    El utxo_set tiene claves que son tuplas (tx_id, index).
    JSON no soporta tuplas como claves, así que las convertimos
    a strings con el formato "tx_id:index" y al cargar las separamos.
    """
    _ensure_dir()

    serializable = {}
    for (tx_id, index), utxo in utxo_set.items():
        key = f"{tx_id}:{index}"          # "abc123:0"
        serializable[key] = utxo.to_dict()

    with open(_path("utxo_set.json"), "w") as f:
        json.dump(serializable, f, indent=2)

    print(f"💾 UTXO set guardado ({len(utxo_set)} entradas)")


def save_mempool(pending_transactions):
    """
    Guarda las transacciones pendientes en mempool.json.
    """
    _ensure_dir()
    data = [tx.to_dict() for tx in pending_transactions]

    with open(_path("mempool.json"), "w") as f:
        json.dump(data, f, indent=2)

    print(f"💾 Mempool guardada ({len(pending_transactions)} TXs)")


def save_all(blockchain):
    """Atajo para guardar todo de una vez."""
    save_chain(blockchain.chain)
    save_utxo_set(blockchain.utxo_set)
    save_mempool(blockchain.pending_transactions)


# ==============================================================================
# CARGAR
# ==============================================================================

def load_chain():
    """
    Carga chain.json y reconstruye la lista de objetos Block.
    Devuelve None si el archivo no existe (primera vez que corre el nodo).
    """
    from core.block import Block

    path = _path("chain.json")
    if not os.path.exists(path):
        return None

    with open(path, "r") as f:
        data = json.load(f)

    chain = [Block.from_dict(block_data) for block_data in data]
    print(f"📂 Cadena cargada ({len(chain)} bloques)")
    return chain


def load_utxo_set():
    """
    Carga utxo_set.json y reconstruye el dict con claves (tx_id, index).
    Devuelve None si el archivo no existe.
    """
    from core.transaction import TxOutput

    path = _path("utxo_set.json")
    if not os.path.exists(path):
        return None

    with open(path, "r") as f:
        data = json.load(f)

    utxo_set = {}
    for key_str, utxo_data in data.items():
        # Separamos "tx_id:index" → ("tx_id", index)
        # El tx_id puede contener ":" si es hex, así que separamos solo en el ÚLTIMO ":"
        last_colon = key_str.rfind(":")
        tx_id = key_str[:last_colon]
        index = int(key_str[last_colon + 1:])
        utxo_set[(tx_id, index)] = TxOutput.from_dict(utxo_data)

    print(f"📂 UTXO set cargado ({len(utxo_set)} entradas)")
    return utxo_set


def load_mempool():
    """
    Carga mempool.json y reconstruye la lista de transacciones pendientes.
    Devuelve lista vacía si el archivo no existe.
    """
    from core.transaction import Transaction

    path = _path("mempool.json")
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r") as f:
            content = f.read().strip()
        if not content:
            return []
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        print("⚠️  mempool.json corrupto, ignorando")
        return []

    txs = [Transaction.from_dict(tx_data) for tx_data in data]
    print(f"📂 Mempool cargada ({len(txs)} TXs)")
    return txs


def has_saved_data():
    """Devuelve True si ya existe una blockchain guardada en disco."""
    return os.path.exists(_path("chain.json"))