import hashlib


class Block:

    def __init__(self, index, timestamp, transactions, previous_hash, difficulty=2, nonce=0, hash=None):
        self.index = index
        self.timestamp = timestamp
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.difficulty = difficulty
        self.nonce = nonce

        # Si nos pasan el hash (porque lo cargamos de disco), lo usamos directamente.
        # Si no, significa que es un bloque nuevo y hay que minarlo.
        if hash is not None:
            self.hash = hash
        else:
            self.hash = self.mine_block()

    def calculate_hash(self):
        """Convierte las transacciones a dict para hashearlas de forma consistente."""
        tx_data = [
            tx.to_dict() if hasattr(tx, "to_dict") else tx
            for tx in self.transactions
        ]
        block_string = f"{self.index}{self.timestamp}{tx_data}{self.previous_hash}{self.nonce}"
        return hashlib.sha256(block_string.encode()).hexdigest()

    def mine_block(self):
        """Busca un nonce tal que el hash empiece con N ceros (Proof of Work)."""
        target = "0" * self.difficulty
        hash_attempt = self.calculate_hash()

        while not hash_attempt.startswith(target):
            self.nonce += 1
            hash_attempt = self.calculate_hash()

        return hash_attempt

    # ------------------------------------------------------------------
    # SERIALIZACIÓN
    # ------------------------------------------------------------------

    def to_dict(self):
        """Convierte el bloque a un diccionario JSON-serializable."""
        return {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "transactions":  [
                tx.to_dict() if hasattr(tx, "to_dict") else tx
                for tx in self.transactions
            ],
            "previous_hash": self.previous_hash,
            "difficulty":    self.difficulty,
            "nonce":         self.nonce,
            "hash":          self.hash,
        }

    @staticmethod
    def from_dict(data):
        """
        Reconstruye un bloque desde un diccionario.
        Importamos Transaction acá adentro para evitar imports circulares.
        """
        from core.transaction import Transaction

        transactions = [
            Transaction.from_dict(tx) if isinstance(tx, dict) else tx
            for tx in data["transactions"]
        ]

        # Le pasamos el hash guardado → el __init__ NO vuelve a minar
        return Block(
            index=data["index"],
            timestamp=data["timestamp"],
            transactions=transactions,
            previous_hash=data["previous_hash"],
            difficulty=data["difficulty"],
            nonce=data["nonce"],
            hash=data["hash"],
        )