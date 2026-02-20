from core.block import Block
import time
from core.transaction import Transaction, TxInput, TxOutput
import copy
import storage.storage as storage




MAX_TX_PER_BLOCK = 5
MINING_REWARD = 50


class Blockchain:
    def __init__(self, difficulty):
        self.difficulty = difficulty
        self.chain = []
        self.pending_transactions = []
        self.utxo_set = {}  # {(tx_id, output_index): TxOutput}

        if storage.has_saved_data():
            # ── Caso A: ya existe una blockchain guardada → la cargamos ──
            print("📂 Encontré datos en disco, cargando blockchain...")
            self.chain                = storage.load_chain()
            self.utxo_set             = storage.load_utxo_set()
            self.pending_transactions = storage.load_mempool()
            print("✅ Blockchain restaurada desde disco")
        else:
            # ── Caso B: primera vez → creamos el bloque génesis ──
            print("🌱 No hay datos en disco, creando blockchain nueva...")
            self.create_genesis_block()
            storage.save_all(self)   # guardamos el estado inicial

    # ======================
    # TRANSACTIONS
    # ======================

    def add_transaction(self, tx):
        print("\n--- ADD TRANSACTION ---")
        print("TX ID:", tx.id)

        for tx_input in tx.inputs:
            key = (tx_input.tx_id, tx_input.output_index)

            if key not in self.utxo_set:
                print("❌ UTXO inexistente:", key)
                return False

            if key in self.get_locked_utxos():
                print("❌ UTXO lockeado:", key)
                return False

        input_sum = sum(self.utxo_set[(i.tx_id, i.output_index)].amount for i in tx.inputs)
        output_sum = sum(o.amount for o in tx.outputs)

        print("Input sum:", input_sum)
        print("Output sum:", output_sum)

        if input_sum < output_sum:
            print("❌ Input < Output")
            return False

        try:
            tx.verify(self.utxo_set)
        except Exception as e:
            print("❌ Verify falló:", e)
            return False

        print("✅ TX aceptada")
        self.pending_transactions.append(tx)
        storage.save_mempool(self.pending_transactions)  # persistir mempool
        return True

    def get_locked_utxos(self):
        locked = set()
        for tx in self.pending_transactions:
            for inp in tx.inputs:
                locked.add((inp.tx_id, inp.output_index))
        return locked

    # ======================
    # MINING
    # ======================

    def get_tx_fee(self, tx):
        total_input = 0
        for tx_input in tx.inputs:
            key = (tx_input.tx_id, tx_input.output_index)
            utxo = self.utxo_set[key]
            total_input += utxo.amount
        total_output = sum(out.amount for out in tx.outputs)
        return total_input - total_output

    def mine_pending_transactions(self, miner_pubkey_pem):
        utxo_snapshot = copy.deepcopy(self.utxo_set)

        # 1. Seleccionar TXs por fee
        sorted_txs = sorted(
            self.pending_transactions,
            key=lambda tx: self.get_tx_fee(tx),
            reverse=True
        )
        selected = []

        for tx in sorted_txs:
            if len(selected) == MAX_TX_PER_BLOCK:
                break
            try:
                tx.verify(utxo_snapshot)
            except Exception:
                continue
            self.apply_transaction(tx, utxo_snapshot)
            selected.append(tx)

        # 2. Calcular fees
        fees_collected = sum(self.get_tx_fee(tx) for tx in selected)

        # 3. Coinbase
        coinbase_tx = Transaction(
            inputs=[],
            outputs=[
                TxOutput(
                    amount=MINING_REWARD + fees_collected,
                    recipient_public_key_pem=miner_pubkey_pem
                )
            ]
        )

        # ✅ FIX: el bloque incluye coinbase + selected
        txs = [coinbase_tx] + selected

        block = Block(
            index=len(self.chain),
            timestamp=time.time(),
            transactions=txs,
            previous_hash=self.get_latest_block().hash,
            difficulty=self.difficulty
        )

        # add_block valida y aplica
        if not self.add_block(block):
            print("Bloque minado inválido")
            return False

        # Limpiar mempool de las TXs que quedaron en el bloque
        for tx in selected:
            if tx in self.pending_transactions:
                self.pending_transactions.remove(tx)

        storage.save_mempool(self.pending_transactions)  # persistir mempool actualizada
        return True

    # ======================
    # APPLY TRANSACTION (UTXO_SET)
    # ======================

    def apply_transaction(self, tx, utxo_set):
        for tx_input in tx.inputs:
            key = (tx_input.tx_id, tx_input.output_index)
            if key in utxo_set:
                del utxo_set[key]

        for index, tx_output in enumerate(tx.outputs):
            key = (tx.id, index)
            utxo_set[key] = tx_output

    # ======================
    # BLOCKS
    # ======================

    def create_genesis_block(self):
        genesis_output = TxOutput(amount=1000, recipient_public_key_pem=b"genesis")
        genesis_tx = Transaction(inputs=[], outputs=[genesis_output])

        # ─────────────────────────────────────────────────────────────
        # TIMESTAMP FIJO: todos los nodos deben producir el mismo
        # génesis, para que sus cadenas sean compatibles entre sí.
        # Si cada nodo usara time.time() obtendría un hash diferente
        # y nunca podrían sincronizarse.
        # ─────────────────────────────────────────────────────────────
        GENESIS_TIMESTAMP = 1_700_000_000  # timestamp fijo para toda la red

        block = Block(
            index=0,
            timestamp=GENESIS_TIMESTAMP,
            transactions=[genesis_tx],
            previous_hash="0",
            difficulty=self.difficulty
        )

        self.chain.append(block)
        self.apply_transaction(genesis_tx, self.utxo_set)

    def get_latest_block(self):
        return self.chain[-1]

    def validate_block(self, block) -> bool:
        latest = self.get_latest_block()

        if block.previous_hash != latest.hash:
            return False

        if block.index != latest.index + 1:
            return False

        if block.calculate_hash() != block.hash:
            return False

        genesis_difficulty = self.chain[0].difficulty
        if not block.hash.startswith("0" * genesis_difficulty):
            return False

        if block.difficulty < genesis_difficulty:
            return False

        transactions = block.transactions

        if len(transactions) == 0:
            return False

        # ✅ FIX: las transacciones ya son objetos Transaction, no dicts
        coinbase = transactions[0]
        if not coinbase.is_coinbase():
            return False

        utxo_snapshot = copy.deepcopy(self.utxo_set)
        fees_total = 0

        for tx in transactions[1:]:
            # ✅ FIX: manejar tanto objetos como dicts
            if isinstance(tx, dict):
                tx = Transaction.from_dict(tx)

            try:
                valid, fee = tx.verify(utxo_snapshot)
            except Exception as e:
                print("TX inválida en validate_block:", e)
                return False

            if not valid:
                return False

            self.apply_transaction(tx, utxo_snapshot)
            fees_total += fee

        coinbase_amount = coinbase.outputs[0].amount if coinbase.outputs else 0

        if coinbase_amount != MINING_REWARD + fees_total:
            return False

        return True

    def add_block(self, block):
        if not self.validate_block(block):
            print("Bloque inválido")
            return False

        # Aplicar todas las transacciones al UTXO set real
        for tx in block.transactions:
            if isinstance(tx, dict):
                tx = Transaction.from_dict(tx)
            self.apply_transaction(tx, self.utxo_set)

        self.chain.append(block)
        storage.save_chain(self.chain)       # persistir cadena
        storage.save_utxo_set(self.utxo_set) # persistir UTXOs
        return True

    # ======================
    # CHAIN VALIDATION
    # ======================

    def rebuild_utxo_set(self, chain=None):
        """
        Recorre una cadena de bloques desde el génesis y reconstruye
        el UTXO set resultante. No modifica self.utxo_set.

        Parámetros:
          chain — lista de bloques a recorrer. Si es None usa self.chain.

        Devuelve:
          dict {(tx_id, index): TxOutput} con todos los UTXOs no gastados.

        Este método es la fuente de verdad del estado: dado cualquier cadena
        válida, rebuild_utxo_set() siempre produce el mismo UTXO set.
        """
        if chain is None:
            chain = self.chain

        utxo = {}

        for block in chain:
            for tx in block.transactions:
                if isinstance(tx, dict):
                    tx = Transaction.from_dict(tx)
                self.apply_transaction(tx, utxo)

        return utxo

    def validate_chain(self, chain=None):
        """
        Valida una cadena de bloques completa desde el génesis.
        No modifica self.utxo_set ni ningún otro estado interno.

        Parámetros:
          chain — lista de bloques a validar. Si es None usa self.chain.

        Qué verifica por cada bloque:
          - Hash previo correcto (encadenamiento)
          - Proof of Work válido
          - Timestamp no retrocede
          - Coinbase en primera posición y con monto correcto
          - Todas las TXs con firmas y UTXOs válidos
        """
        if chain is None:
            chain = self.chain

        # Reconstruimos el UTXO set localmente para validar TXs
        utxo = {}

        for i, block in enumerate(chain):

            # ── Validaciones de encadenamiento ──
            if i == 0:
                if block.previous_hash != "0":
                    print("Genesis inválido")
                    return False
            else:
                prev = chain[i - 1]

                if block.previous_hash != prev.hash:
                    print(f"Bloque {i}: hash previo inválido")
                    return False

                if not block.hash.startswith("0" * block.difficulty):
                    print(f"Bloque {i}: Proof of Work inválido")
                    return False

                if block.timestamp < prev.timestamp:
                    print(f"Bloque {i}: timestamp inválido")
                    return False

            # ── Validaciones de transacciones ──
            fees_collected = 0
            coinbase_tx    = None
            coinbase_seen  = False

            for tx_index, tx in enumerate(block.transactions):
                if isinstance(tx, dict):
                    tx = Transaction.from_dict(tx)

                if tx.is_coinbase():
                    # Génesis: permitimos múltiples coinbases de funding inicial
                    if i == 0:
                        self.apply_transaction(tx, utxo)
                        continue

                    if tx_index != 0:
                        print(f"Bloque {i}: coinbase no está en posición 0")
                        return False
                    if coinbase_seen:
                        print(f"Bloque {i}: múltiples coinbase")
                        return False

                    coinbase_seen = True
                    coinbase_tx   = tx
                    continue  # la aplicamos después de calcular las fees

                # TX normal: verificar firmas y UTXOs
                try:
                    valid, fee = tx.verify(utxo)
                except Exception as e:
                    print(f"Bloque {i}: TX inválida — {e}")
                    return False

                fees_collected += fee
                self.apply_transaction(tx, utxo)

            # Validar monto de coinbase (excepto génesis)
            if coinbase_tx is not None:
                if i > 0:
                    expected = MINING_REWARD + fees_collected
                    actual   = coinbase_tx.outputs[0].amount if coinbase_tx.outputs else 0
                    if actual != expected:
                        print(f"Bloque {i}: coinbase inválida — esperado={expected}, obtenido={actual}")
                        return False
                self.apply_transaction(coinbase_tx, utxo)

        return True