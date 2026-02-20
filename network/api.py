"""
api.py — API REST para el nodo blockchain.

Expone la blockchain y la red P2P a través de HTTP.
Se corre en un thread separado para no bloquear el nodo P2P.
"""

from flask import Flask, jsonify, request


def create_app(blockchain, node, miner=None):
    """
    Fábrica de la app Flask.
    Recibe blockchain y node como dependencias — sin variables globales.
    """
    app = Flask(__name__)

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    def ok(data, status=200):
        return jsonify({"ok": True, "data": data}), status

    def err(message, status=400):
        return jsonify({"ok": False, "error": message}), status

    # ──────────────────────────────────────────────
    # NODO
    # ──────────────────────────────────────────────

    @app.route("/status")
    def status():
        """Estado general del nodo — primer endpoint a visitar."""
        return ok({
            "node_port":    node.port,
            "peers":        list(node.peers),
            "chain_length": len(blockchain.chain),
            "pending_txs":  len(blockchain.pending_transactions),
            "utxo_count":   len(blockchain.utxo_set),
        })

    @app.route("/connect", methods=["POST"])
    def connect():
        """
        Conectarse a un peer.
        Body: { "host": "127.0.0.1", "port": 6001 }
        """
        body = request.get_json()
        if not body:
            return err("Body JSON requerido")

        host = body.get("host")
        port = body.get("port")
        if not host or not port:
            return err("Faltan campos: host, port")

        success = node.connect_to_peer(host, int(port))
        if success:
            return ok({"message": f"Conectado a {host}:{port}"})
        else:
            return err(f"No se pudo conectar a {host}:{port}")

    # ──────────────────────────────────────────────
    # CADENA
    # ──────────────────────────────────────────────

    @app.route("/chain")
    def chain():
        """Devuelve la cadena completa de bloques."""
        return ok({
            "length": len(blockchain.chain),
            "chain":  [_serialize_block(b) for b in blockchain.chain],
        })

    @app.route("/block/<int:index>")
    def block_by_index(index):
        """
        Bloque por índice.
        GET /block/0  → génesis
        GET /block/1  → primer bloque minado
        """
        if index < 0 or index >= len(blockchain.chain):
            return err(f"Bloque {index} no existe", 404)
        return ok(_serialize_block(blockchain.chain[index]))

    @app.route("/block/hash/<hash_str>")
    def block_by_hash(hash_str):
        """Busca un bloque por su hash."""
        for b in blockchain.chain:
            if b.hash == hash_str:
                return ok(_serialize_block(b))
        return err("Bloque no encontrado", 404)

    # ──────────────────────────────────────────────
    # TRANSACCIONES
    # ──────────────────────────────────────────────

    @app.route("/mempool")
    def mempool():
        """Transacciones pendientes de ser minadas."""
        return ok({
            "count":        len(blockchain.pending_transactions),
            "transactions": [_serialize_tx(tx) for tx in blockchain.pending_transactions],
        })

    @app.route("/transaction", methods=["POST"])
    def new_transaction():
        """
        Recibe una transacción ya firmada y la propaga a la red.
        Body: el dict que devuelve tx.to_dict()
        """
        from core.transaction import Transaction

        body = request.get_json()
        if not body:
            return err("Body JSON requerido")

        try:
            tx = Transaction.from_dict(body)
        except Exception as e:
            return err(f"TX mal formada: {e}")

        success = node.announce_transaction(tx)
        if success:
            return ok({"tx_id": tx.id, "message": "TX aceptada y propagada"}, 201)
        else:
            return err("TX inválida (UTXO inexistente, firma incorrecta, o doble gasto)")

    @app.route("/transaction/<tx_id>")
    def get_transaction(tx_id):
        """
        Busca una TX en la cadena (confirmada) o en la mempool (pendiente).
        """
        for block in blockchain.chain:
            for tx in block.transactions:
                if tx.id == tx_id:
                    return ok({
                        "status":      "confirmada",
                        "block_index": block.index,
                        "block_hash":  block.hash,
                        "transaction": _serialize_tx(tx),
                    })

        for tx in blockchain.pending_transactions:
            if tx.id == tx_id:
                return ok({"status": "pendiente", "transaction": _serialize_tx(tx)})

        return err("Transacción no encontrada", 404)

    # ──────────────────────────────────────────────
    # WALLET / UTXOs
    # ──────────────────────────────────────────────

    @app.route("/utxos")
    def all_utxos():
        """Lista todos los UTXOs del sistema — el estado completo del dinero."""
        utxos = []
        for (tx_id, idx), utxo in blockchain.utxo_set.items():
            pk = utxo.recipient_public_key
            if isinstance(pk, bytes):
                pk = pk.decode(errors="replace")
            utxos.append({
                "tx_id":  tx_id,
                "index":  idx,
                "amount": utxo.amount,
                "owner":  pk,
            })
        return ok({"count": len(utxos), "utxos": utxos})

    @app.route("/balance", methods=["POST"])
    def balance():
        """
        Balance de una wallet.
        Body: { "address": "-----BEGIN PUBLIC KEY-----\\n..." }
        Usamos POST porque la clave pública PEM es larga y tiene caracteres especiales.
        """
        body = request.get_json()
        if not body or "address" not in body:
            return err("Falta campo: address")

        address = body["address"]
        if isinstance(address, str):
            address = address.encode()

        total = 0
        utxos = []
        for (tx_id, idx), utxo in blockchain.utxo_set.items():
            if utxo.recipient_public_key == address:
                total += utxo.amount
                utxos.append({"tx_id": tx_id, "index": idx, "amount": utxo.amount})

        return ok({"balance": total, "utxo_count": len(utxos), "utxos": utxos})

    # ──────────────────────────────────────────────
    # MINADO
    # ──────────────────────────────────────────────

    @app.route("/mine", methods=["POST"])
    def mine():
        """
        Mina un bloque con las TXs pendientes y lo anuncia a la red.
        Body: { "miner_address": "-----BEGIN PUBLIC KEY-----\\n..." }
        """
        body = request.get_json()
        if not body:
            return err("Body JSON requerido")

        miner_address = body.get("miner_address")
        if not miner_address:
            return err("Falta campo: miner_address")

        if isinstance(miner_address, str):
            miner_address = miner_address.encode()

        success = blockchain.mine_pending_transactions(miner_address)
        if not success:
            return err("No se pudo minar")

        new_block = blockchain.get_latest_block()
        node.announce_block(new_block)   # avisar a los peers

        return ok({
            "message":    f"Bloque #{new_block.index} minado exitosamente",
            "block_hash": new_block.hash,
            "nonce":      new_block.nonce,
            "tx_count":   len(new_block.transactions),
        }, 201)

    # ──────────────────────────────────────────────
    # CONTROL DEL MINADO AUTOMÁTICO
    # ──────────────────────────────────────────────

    @app.route("/mining/status")
    def mining_status():
        """Estado del minado automático: si corre, cuántos bloques minó, etc."""
        if miner is None:
            return ok({"available": False, "message": "Minado automático no configurado"})
        return ok({"available": True, **miner.status()})

    @app.route("/mining/stop", methods=["POST"])
    def mining_stop():
        """Pausa el minado automático."""
        if miner is None:
            return err("Minado automático no disponible")
        miner.stop()
        return ok({"running": False, "message": "Minado pausado"})

    @app.route("/network")
    def network():
        """Mapa de toda la red: todos los nodos conectados con su estado."""
        return ok(node.get_network_map())

    @app.route("/mining/start", methods=["POST"])
    def mining_start():
        """Reanuda el minado automático si estaba pausado."""
        if miner is None:
            return err("Minado automático no disponible")
        miner.resume()
        return ok({"running": True, "message": "Minado reanudado"})
    # SERIALIZADORES INTERNOS
    # ──────────────────────────────────────────────

    def _serialize_block(block):
        return {
            "index":         block.index,
            "hash":          block.hash,
            "previous_hash": block.previous_hash,
            "timestamp":     block.timestamp,
            "difficulty":    block.difficulty,
            "nonce":         block.nonce,
            "tx_count":      len(block.transactions),
            "transactions":  [_serialize_tx(tx) for tx in block.transactions],
        }

    def _serialize_tx(tx):
        inputs = []
        for inp in tx.inputs:
            inputs.append({
                "tx_id":        inp.tx_id,
                "output_index": inp.output_index,
                "signature":    inp.signature.hex() if inp.signature else None,
            })

        outputs = []
        for out in tx.outputs:
            pk = out.recipient_public_key
            if isinstance(pk, bytes):
                pk = pk.decode(errors="replace")
            outputs.append({"amount": out.amount, "recipient_public_key": pk})

        return {
            "id":          tx.id,
            "is_coinbase": tx.is_coinbase(),
            "inputs":      inputs,
            "outputs":     outputs,
        }

    # ──────────────────────────────────────────────
    # FAUCET — solo para testing/desarrollo
    # ──────────────────────────────────────────────

    @app.route("/fund", methods=["POST"])
    def fund():
        """
        Inyecta coins directamente en el UTXO set de todos los nodos.
        Solo para desarrollo/testing.
        Body: { "address": "-----BEGIN PUBLIC KEY-----...", "amount": 1000 }
        """
        body = request.get_json()
        if not body:
            return err("Body JSON requerido")

        address = body.get("address")
        amount  = int(body.get("amount", 100))

        if not address:
            return err("Falta campo: address")

        if isinstance(address, str):
            address = address.encode()

        from core.transaction import Transaction, TxOutput
        import hashlib, time as _time

        tx_out = TxOutput(amount=amount, recipient_public_key_pem=address)
        tx     = Transaction(inputs=[], outputs=[tx_out])
        tx.id  = hashlib.sha256(
            f"fund-{_time.time()}-{address[:20]}".encode()
        ).hexdigest()

        # Inyectar en UTXO set y génesis
        blockchain.utxo_set[(tx.id, 0)] = tx_out
        blockchain.chain[0].transactions.append(tx)

        import storage.storage as storage
        storage.save_utxo_set(blockchain.utxo_set)

        return ok({"tx_id": tx.id, "amount": amount}, 201)

    register_p2p_routes(app, blockchain, node)
    return app


def register_p2p_routes(app, blockchain, node):
    """
    Registra los endpoints P2P en la app Flask.
    Llamar desde create_app() después de crear la app.
    """

    @app.route("/p2p/handshake", methods=["POST"])
    def p2p_handshake():
        payload = request.get_json() or {}
        node.handle_handshake(payload)
        # Responder con nuestra info
        return jsonify({
            "ok":      True,
            "url":     node.public_url,
            "port":    node.port,
            "version": "0.2",
            "chain_length": len(blockchain.chain),
        })

    @app.route("/p2p/block", methods=["POST"])
    def p2p_block():
        payload = request.get_json() or {}
        node.handle_new_block(payload)
        return jsonify({"ok": True})

    @app.route("/p2p/tx", methods=["POST"])
    def p2p_tx():
        payload = request.get_json() or {}
        node.handle_new_tx(payload)
        return jsonify({"ok": True})

    @app.route("/p2p/chain")
    def p2p_chain():
        return jsonify({"chain": node.handle_get_chain()})

    @app.route("/p2p/peers")
    def p2p_peers():
        return jsonify({"peers": node.handle_get_peers()})