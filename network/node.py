"""
node.py — Capa de red P2P via HTTP.

Fixes en esta versión:
  1. Cuando un bloque es rechazado por viejo, pide la cadena al remitente
  2. La dificultad se valida contra NETWORK_DIFFICULTY (no viene del bloque)
  3. Propagación correcta de peers a toda la red
  4. Endpoint /network para ver todos los nodos
"""

import threading
import time
import json
import urllib.request
import urllib.error

VERSION = "0.2"

# Versión mínima aceptada — nodos con versión menor son rechazados
MIN_VERSION = "0.2"

# Penalización de peers — cuántos bloques inválidos antes de desconectar
MAX_PEER_STRIKES = 3

# Máximo desfasaje de tiempo permitido en un bloque (2 horas, igual que Bitcoin)
MAX_TIMESTAMP_DRIFT = 2 * 60 * 60

# La dificultad se lee del bloque génesis — no está hardcodeada acá
# Todos los nodos que compartan el mismo génesis usan la misma dificultad


def http_post(url, body, timeout=5):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        res = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(res.read()), True
    except Exception:
        return None, False


def http_get(url, timeout=5):
    try:
        res = urllib.request.urlopen(url, timeout=timeout)
        return json.loads(res.read()), True
    except Exception:
        return None, False


class Node:

    def __init__(self, host, port, blockchain):
        self.host       = host
        self.port       = port
        self.blockchain = blockchain
        self.public_url = f"http://127.0.0.1:{port}"
        self.peers: set        = set()   # URLs base de peers conocidos
        self._peer_strikes: dict = {}     # {peer_url: cantidad de bloques inválidos}
        self._lock             = threading.Lock()
        self._running          = False

    # ──────────────────────────────────────────
    # ARRANCAR / DETENER
    # ──────────────────────────────────────────

    def start(self):
        self._running = True
        print(f"[Node:{self.port}] 🟢 Nodo HTTP arrancado en puerto {self.port}")
        self._load_peers_from_disk()

    def _load_peers_from_disk(self):
        """Al arrancar intenta reconectarse a los peers conocidos del disco."""
        from storage import storage
        peers_guardados = storage.load_peers()
        if not peers_guardados:
            return
        print(f"[Node:{self.port}] 📋 {len(peers_guardados)} peers guardados en disco, reconectando...")
        for peer_url in peers_guardados:
            if peer_url != self.public_url:
                threading.Thread(
                    target=self.connect_to_peer,
                    kwargs={"peer_host": None, "peer_port": None, "peer_url": peer_url},
                    daemon=True
                ).start()

    def stop(self):
        self._running = False
        print(f"[Node:{self.port}] 🔴 Nodo detenido")

    # ──────────────────────────────────────────
    # CONECTAR A UN PEER
    # ──────────────────────────────────────────

    def connect_to_peer(self, peer_host, peer_port, peer_url=None):
        if peer_url is None:
            peer_url = f"http://{peer_host}:{peer_port}"

        with self._lock:
            if peer_url in self.peers or peer_url == self.public_url:
                return False

        body = {"url": self.public_url, "port": self.port, "version": VERSION}
        res, ok = http_post(f"{peer_url}/p2p/handshake", body)

        if not ok:
            print(f"[Node:{self.port}] ❌ No pude conectar a {peer_url}")
            return False

        with self._lock:
            self.peers.add(peer_url)

        # Persistir peers en disco para reconexión sin bootstrap
        from storage import storage
        with self._lock:
            storage.save_peers(self.peers)

        print(f"[Node:{self.port}] ✅ Conectado a {peer_url}")

        # Sincronizar cadena
        self._sync_chain_from(peer_url)

        # Descubrir todos los peers de la red
        self._discover_peers_from(peer_url)

        return True

    # ──────────────────────────────────────────
    # HANDLERS — llamados desde api.py
    # ──────────────────────────────────────────

    def handle_handshake(self, payload):
        """
        Otro nodo se presenta. Lo registramos y propagamos
        su existencia a TODOS nuestros peers existentes.
        """
        peer_url = payload.get("url")
        if not peer_url or peer_url == self.public_url:
            return False

        # Validar versión de protocolo
        peer_version = payload.get("version", "0.0")
        if tuple(int(x) for x in peer_version.split(".")) < tuple(int(x) for x in MIN_VERSION.split(".")):
            print(f"[Node:{self.port}] ❌ Peer {peer_url} rechazado: versión {peer_version} < {MIN_VERSION}")
            return False

        with self._lock:
            es_nuevo = peer_url not in self.peers
            self.peers.add(peer_url)

        if es_nuevo:
            print(f"[Node:{self.port}] 🤝 Nuevo peer: {peer_url}")

            # FIX: avisar a TODOS los peers existentes sobre el nuevo nodo
            # y al nuevo nodo sobre todos nuestros peers
            threading.Thread(
                target=self._propagar_nuevo_peer,
                args=(peer_url,),
                daemon=True
            ).start()

        return True

    def _propagar_nuevo_peer(self, nuevo_peer_url):
        """
        Cuando llega un peer nuevo:
        1. Le mandamos nuestra lista completa de peers (para que se conecte a todos)
        2. Avisamos a todos nuestros peers que existe el nuevo (para que se conecten)
        """
        time.sleep(0.3)

        # 1. Mandamos nuestro handshake al nuevo peer (conexión bidireccional)
        body = {"url": self.public_url, "port": self.port, "version": VERSION}
        http_post(f"{nuevo_peer_url}/p2p/handshake", body)

        # 2. Avisamos a todos nuestros peers sobre el nuevo
        with self._lock:
            peers_actuales = list(self.peers - {nuevo_peer_url})

        for peer_url in peers_actuales:
            # Le decimos al peer existente que hay un nodo nuevo
            body = {"url": nuevo_peer_url, "port": 0, "version": VERSION}
            http_post(f"{peer_url}/p2p/handshake", body)

        # 3. Le decimos al nuevo peer sobre todos nuestros peers
        for peer_url in peers_actuales:
            body = {"url": peer_url, "port": 0, "version": VERSION}
            http_post(f"{nuevo_peer_url}/p2p/handshake", body)

    def handle_new_block(self, payload):
        """
        FIX: si el bloque es más nuevo que el nuestro,
        pedimos la cadena completa al remitente.
        """
        from core.block import Block

        # Validar dificultad contra el génesis
        genesis_difficulty = self.blockchain.chain[0].difficulty
        block_difficulty   = payload.get("difficulty", 0)
        if block_difficulty < genesis_difficulty:
            print(f"[Node:{self.port}] ❌ Bloque rechazado: dificultad {block_difficulty} < {genesis_difficulty} (génesis)")
            return

        # Validar timestamp — no aceptar bloques más de 2hs en el futuro
        import time as _time
        block_timestamp = payload.get("timestamp", 0)
        if block_timestamp > _time.time() + MAX_TIMESTAMP_DRIFT:
            print(f"[Node:{self.port}] ❌ Bloque rechazado: timestamp demasiado en el futuro")
            return

        sender_url = payload.get("_sender_url")

        try:
            block  = Block.from_dict(payload)
            latest = self.blockchain.get_latest_block()

            if block.previous_hash == latest.hash:
                # Es el siguiente bloque esperado
                added = self.blockchain.add_block(block)
                if added:
                    print(f"[Node:{self.port}] 📦 Bloque #{block.index} agregado")
                    # Resetear strikes del peer si mandó un bloque válido
                    if sender_url:
                        with self._lock:
                            self._peer_strikes[sender_url] = 0
                    self.broadcast_block(block, exclude=sender_url)
                else:
                    print(f"[Node:{self.port}] ❌ Bloque #{block.index} inválido")
                    self._penalizar_peer(sender_url)

            elif block.index > latest.index:
                # FIX: el bloque es más nuevo — estamos atrasados
                # Pedir cadena al remitente y a todos los peers
                print(f"[Node:{self.port}] 🔄 Atrasado (tengo #{latest.index}, recibí #{block.index}), sincronizando...")
                if sender_url:
                    threading.Thread(
                        target=self._sync_chain_from,
                        args=(sender_url,),
                        daemon=True
                    ).start()
                else:
                    threading.Thread(
                        target=self._sync_from_all,
                        daemon=True
                    ).start()

            else:
                print(f"[Node:{self.port}] ⚠️  Bloque #{block.index} ignorado (viejo o fork)")

        except Exception as e:
            print(f"[Node:{self.port}] ❌ Error procesando bloque: {e}")

    def _penalizar_peer(self, peer_url):
        """
        Suma un strike al peer. Si supera MAX_PEER_STRIKES lo desconecta.
        Los peers que mandan bloques inválidos repetidamente son maliciosos o buggeados.
        """
        if not peer_url:
            return
        with self._lock:
            strikes = self._peer_strikes.get(peer_url, 0) + 1
            self._peer_strikes[peer_url] = strikes

        print(f"[Node:{self.port}] ⚠️  Strike {strikes}/{MAX_PEER_STRIKES} para {peer_url}")

        if strikes >= MAX_PEER_STRIKES:
            print(f"[Node:{self.port}] 🚫 {peer_url} baneado por bloques inválidos repetidos")
            with self._lock:
                self.peers.discard(peer_url)
                self._peer_strikes.pop(peer_url, None)
            from storage import storage
            with self._lock:
                storage.save_peers(self.peers)

    def handle_new_tx(self, payload):
        from core.transaction import Transaction
        try:
            tx    = Transaction.from_dict(payload)
            added = self.blockchain.add_transaction(tx)
            if added:
                print(f"[Node:{self.port}] 📨 TX {tx.id[:8]}... aceptada")
                sender = payload.get("_sender_url")
                self.broadcast_tx(tx, exclude=sender)
        except Exception as e:
            print(f"[Node:{self.port}] ❌ Error procesando TX: {e}")

    def handle_get_chain(self):
        return [b.to_dict() for b in self.blockchain.chain]

    def handle_get_peers(self):
        with self._lock:
            return list(self.peers)

    # ──────────────────────────────────────────
    # SINCRONIZACIÓN
    # ──────────────────────────────────────────

    def _sync_chain_from(self, peer_url):
        """Descarga y adopta la cadena de un peer si es más larga."""
        res, ok = http_get(f"{peer_url}/p2p/chain")
        if not ok or not res:
            return

        chain_data = res.get("chain", [])
        if len(chain_data) <= len(self.blockchain.chain):
            return

        self._adopt_chain(chain_data, peer_url)

    def _sync_from_all(self):
        """Sincroniza con todos los peers, adopta la cadena más larga."""
        with self._lock:
            peers = list(self.peers)
        for peer_url in peers:
            self._sync_chain_from(peer_url)

    def _adopt_chain(self, chain_data, source_url):
        from core.block import Block
        from core.blockchain import Blockchain
        from storage import storage

        try:
            # Leer dificultad del génesis de la cadena recibida
            genesis_difficulty = chain_data[0].get("difficulty", 0)

            # Verificar que el génesis recibido coincide con el nuestro
            nuestro_genesis_diff = self.blockchain.chain[0].difficulty
            if genesis_difficulty != nuestro_genesis_diff:
                print(f"[Node:{self.port}] ❌ Cadena rechazada: génesis con dificultad distinta ({genesis_difficulty} vs {nuestro_genesis_diff})")
                return

            # Validar que todos los bloques respetan esa dificultad
            for b in chain_data[1:]:
                if b.get("difficulty", 0) < genesis_difficulty:
                    print(f"[Node:{self.port}] ❌ Cadena rechazada: bloque con dificultad inválida")
                    return

            new_chain = [Block.from_dict(b) for b in chain_data]

            temp_bc                      = Blockchain.__new__(Blockchain)
            temp_bc.chain                = new_chain
            temp_bc.utxo_set             = {}
            temp_bc.pending_transactions = []
            temp_bc.difficulty           = genesis_difficulty

            if not temp_bc.validate_chain(new_chain):
                print(f"[Node:{self.port}] ❌ Cadena de {source_url} inválida")
                return

            rebuilt_utxo = temp_bc.rebuild_utxo_set(new_chain)

            # ── Reorg: devolver TXs de bloques descartados a la mempool ──
            # Encontrar el punto de divergencia entre la cadena vieja y la nueva
            vieja = self.blockchain.chain
            fork_index = 0
            for i in range(min(len(vieja), len(new_chain))):
                if vieja[i].hash != new_chain[i].hash:
                    fork_index = i
                    break
            else:
                fork_index = min(len(vieja), len(new_chain))

            # TXs que ya están confirmadas en la nueva cadena
            txs_en_nueva = set()
            for block in new_chain[fork_index:]:
                for tx in block.transactions:
                    if isinstance(tx, dict):
                        from core.transaction import Transaction
                        tx = Transaction.from_dict(tx)
                    if not tx.is_coinbase():
                        txs_en_nueva.add(tx.id)

            # TXs de bloques descartados que no están en la nueva cadena
            txs_recuperadas = 0
            for block in vieja[fork_index:]:
                for tx in block.transactions:
                    if isinstance(tx, dict):
                        from core.transaction import Transaction
                        tx = Transaction.from_dict(tx)
                    if not tx.is_coinbase() and tx.id not in txs_en_nueva:
                        self.blockchain.pending_transactions.append(tx)
                        txs_recuperadas += 1

            if txs_recuperadas > 0:
                print(f"[Node:{self.port}] ♻️  {txs_recuperadas} TXs devueltas a la mempool tras reorg")
                storage.save_mempool(self.blockchain.pending_transactions)

            self.blockchain.chain    = new_chain
            self.blockchain.utxo_set = rebuilt_utxo

            print(f"[Node:{self.port}] ✅ Cadena adoptada: "
                  f"{len(new_chain)} bloques desde {source_url} (fork en bloque #{fork_index})")

            storage.save_all(self.blockchain)

        except Exception as e:
            print(f"[Node:{self.port}] ❌ Error adoptando cadena: {e}")

    def _discover_peers_from(self, peer_url):
        """Pide la lista de peers y se conecta a todos los desconocidos."""
        res, ok = http_get(f"{peer_url}/p2p/peers")
        if not ok or not res:
            return

        for url in res.get("peers", []):
            if url == self.public_url:
                continue
            with self._lock:
                known = url in self.peers
            if not known:
                print(f"[Node:{self.port}] 🔍 Peer descubierto: {url}")
                threading.Thread(
                    target=self.connect_to_peer,
                    kwargs={"peer_host": None, "peer_port": None, "peer_url": url},
                    daemon=True
                ).start()

    # ──────────────────────────────────────────
    # BROADCAST
    # ──────────────────────────────────────────

    def broadcast_block(self, block, exclude=None):
        payload = block.to_dict()
        payload["_sender_url"] = self.public_url
        with self._lock:
            peers = list(self.peers)
        for peer_url in peers:
            if peer_url == exclude:
                continue
            threading.Thread(
                target=http_post,
                args=(f"{peer_url}/p2p/block", payload),
                daemon=True
            ).start()

    def broadcast_tx(self, tx, exclude=None):
        payload = tx.to_dict()
        payload["_sender_url"] = self.public_url
        with self._lock:
            peers = list(self.peers)
        for peer_url in peers:
            if peer_url == exclude:
                continue
            threading.Thread(
                target=http_post,
                args=(f"{peer_url}/p2p/tx", payload),
                daemon=True
            ).start()

    # ──────────────────────────────────────────
    # HELPERS PARA API
    # ──────────────────────────────────────────

    def announce_transaction(self, tx):
        added = self.blockchain.add_transaction(tx)
        if added:
            self.broadcast_tx(tx)
        return added

    def announce_block(self, block):
        self.broadcast_block(block)
        print(f"[Node:{self.port}] 📢 Bloque #{block.index} anunciado")

    def get_network_map(self):
        """
        Devuelve un mapa de toda la red: este nodo + sus peers
        con info de cada uno (cadena, UTXOs, peers de peers).
        """
        with self._lock:
            peers = list(self.peers)

        network = [{
            "url":          self.public_url,
            "chain_length": len(self.blockchain.chain),
            "utxo_count":   len(self.blockchain.utxo_set),
            "peer_count":   len(peers),
            "peers":        peers,
            "es_este_nodo": True,
        }]

        for peer_url in peers:
            res, ok = http_get(f"{peer_url}/status")
            if ok and res and res.get("ok"):
                d = res["data"]
                network.append({
                    "url":          peer_url,
                    "chain_length": d.get("chain_length", "?"),
                    "utxo_count":   d.get("utxo_count", "?"),
                    "peer_count":   len(d.get("peers", [])),
                    "peers":        d.get("peers", []),
                    "es_este_nodo": False,
                })
            else:
                network.append({
                    "url":          peer_url,
                    "chain_length": "?",
                    "utxo_count":   "?",
                    "peer_count":   "?",
                    "peers":        [],
                    "es_este_nodo": False,
                    "sin_respuesta": True,
                })

        return network