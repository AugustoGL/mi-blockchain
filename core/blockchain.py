from core.block import Block
import time
from core.transaction import Transaction, TxInput, TxOutput
import copy
from storage import storage




MAX_TX_PER_BLOCK  = 5
MAX_MEMPOOL_SIZE  = 500
TX_EXPIRY_SECONDS = 24 * 60 * 60

# ── Política monetaria ────────────────────────────────────────────
INITIAL_REWARD      = 50          # coins por bloque al inicio
HALVING_INTERVAL    = 210         # cada cuántos bloques se reduce la recompensa a la mitad
MAX_SUPPLY          = 21_000_000  # emisión máxima total (como Bitcoin)

# ── Ajuste de dificultad ─────────────────────────────────────────
DIFFICULTY_INTERVAL = 10          # ajustar cada N bloques
TARGET_BLOCK_TIME   = 30          # segundos objetivo por bloque

def get_mining_reward(block_index: int) -> float:
    """
    Calcula la recompensa de minado para un bloque dado su índice.
    Cada HALVING_INTERVAL bloques la recompensa se divide a la mitad.
    Bloque 0-209:   50 coins
    Bloque 210-419: 25 coins
    Bloque 420-629: 12.5 coins
    ...
    Cuando la recompensa llega a 0 los mineros solo cobran fees.
    """
    halvings = block_index // HALVING_INTERVAL
    reward   = INITIAL_REWARD / (2 ** halvings)
    return max(0, reward)


class Blockchain:
    def __init__(self, difficulty):
        self.difficulty = difficulty
        self.chain = []
        self.pending_transactions = []
        self.utxo_set = {}       # {(tx_id, output_index): TxOutput}
        self.tx_index = {}       # {tx_id: block_index} — búsqueda O(1) por tx_id

        if storage.has_saved_data():
            # ── Caso A: ya existe una blockchain guardada → la cargamos ──
            print("📂 Encontré datos en disco, cargando blockchain...")
            self.chain                = storage.load_chain()
            self.utxo_set             = storage.load_utxo_set()
            self.pending_transactions = storage.load_mempool()
            self._rebuild_tx_index()
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

        # Límite de mempool — rechazar si está llena
        if len(self.pending_transactions) >= MAX_MEMPOOL_SIZE:
            print(f"❌ Mempool llena ({MAX_MEMPOOL_SIZE} TXs), TX rechazada")
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

        # 0. Limpiar TXs expiradas antes de minar
        ahora = time.time()
        antes = len(self.pending_transactions)
        self.pending_transactions = [
            tx for tx in self.pending_transactions
            if ahora - tx.timestamp <= TX_EXPIRY_SECONDS
        ]
        expiradas = antes - len(self.pending_transactions)
        if expiradas > 0:
            print(f"🗑️  {expiradas} TXs expiradas eliminadas de la mempool")
            storage.save_mempool(self.pending_transactions)

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

        # 3. Coinbase con halving
        reward      = get_mining_reward(len(self.chain))
        coinbase_tx = Transaction(
            inputs=[],
            outputs=[
                TxOutput(
                    amount=reward + fees_collected,
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

    def get_circulating_supply(self) -> float:
        """Calcula el total de coins emitidos recorriendo los coinbases."""
        total = 0
        for block in self.chain:
            for tx in block.transactions:
                if hasattr(tx, "is_coinbase") and tx.is_coinbase():
                    total += sum(o.amount for o in tx.outputs)
        return total

    def calculate_next_difficulty(self) -> int:
        """
        Ajuste de dificultad cada DIFFICULTY_INTERVAL bloques.
        Compara el tiempo real vs el tiempo objetivo y ajusta.
        Limita el ajuste a x2 o /2 por intervalo (igual que Bitcoin).
        """
        chain_len = len(self.chain)

        # Solo ajustar en el intervalo exacto
        if chain_len < DIFFICULTY_INTERVAL or chain_len % DIFFICULTY_INTERVAL != 0:
            return self.difficulty

        # Tiempo que tardaron los últimos DIFFICULTY_INTERVAL bloques
        bloque_inicio = self.chain[-DIFFICULTY_INTERVAL]
        bloque_fin    = self.chain[-1]
        tiempo_real   = bloque_fin.timestamp - bloque_inicio.timestamp
        tiempo_obj    = TARGET_BLOCK_TIME * DIFFICULTY_INTERVAL

        # Limitar ajuste a factor 2 en cualquier dirección
        if tiempo_real < tiempo_obj / 2:
            tiempo_real = tiempo_obj / 2
        if tiempo_real > tiempo_obj * 2:
            tiempo_real = tiempo_obj * 2

        nueva = round(self.difficulty * tiempo_obj / tiempo_real)
        nueva = max(1, nueva)  # mínimo dificultad 1

        if nueva != self.difficulty:
            print(f"⚡ Dificultad ajustada: {self.difficulty} → {nueva} "                  f"(tiempo real={tiempo_real:.0f}s, objetivo={tiempo_obj}s)")

        return nueva

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

        # Rechazar bloques con timestamp más de 2 horas en el futuro (igual que Bitcoin)
        if block.timestamp > time.time() + 7200:
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
        expected_reward = get_mining_reward(len(self.chain))  # índice del bloque que se va a agregar

        if coinbase_amount != expected_reward + fees_total:
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

        # Indexar TXs del nuevo bloque para búsqueda O(1)
        for tx in block.transactions:
            if hasattr(tx, "id"):
                self.tx_index[tx.id] = block.index

        # Ajustar dificultad si corresponde
        nueva_dificultad = self.calculate_next_difficulty()
        if nueva_dificultad != self.difficulty:
            self.difficulty = nueva_dificultad

        storage.save_chain(self.chain)       # persistir cadena
        storage.save_utxo_set(self.utxo_set) # persistir UTXOs
        return True

    def _rebuild_tx_index(self):
        """Reconstruye el índice tx_id → block_index desde la cadena."""
        self.tx_index = {}
        for block in self.chain:
            for tx in block.transactions:
                if hasattr(tx, "id"):
                    self.tx_index[tx.id] = block.index

    def get_transaction(self, tx_id: str):
        """
        Busca una TX por ID en O(1) usando el índice.
        Devuelve (tx, block_index) o (None, None) si no existe.
        """
        block_index = self.tx_index.get(tx_id)
        if block_index is None:
            return None, None
        block = self.chain[block_index]
        for tx in block.transactions:
            if hasattr(tx, "id") and tx.id == tx_id:
                return tx, block_index
        return None, None

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
                    print(f"Bloque {i}: timestamp inválido (retrocede)")
                    return False

                import time as _time
                if block.timestamp > _time.time() + 7200:  # 2 horas
                    print(f"Bloque {i}: timestamp demasiado en el futuro")
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
                    expected = get_mining_reward(i) + fees_collected
                    actual   = coinbase_tx.outputs[0].amount if coinbase_tx.outputs else 0
                    if actual != expected:
                        print(f"Bloque {i}: coinbase inválida — esperado={expected}, obtenido={actual}")
                        return False
                self.apply_transaction(coinbase_tx, utxo)

        return True