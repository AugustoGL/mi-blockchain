import hashlib
import json


def _double_sha256(data: bytes) -> str:
    """SHA256(SHA256(data)) — igual que Bitcoin. Devuelve hex string."""
    return hashlib.sha256(hashlib.sha256(data).digest()).hexdigest()


def _serialize_deterministic(data) -> bytes:
    """JSON con sort_keys=True para serialización consistente entre nodos."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Block:

    def __init__(self, index, timestamp, transactions, previous_hash,
                 difficulty=2, nonce=0, hash=None):
        self.index         = index
        self.timestamp     = timestamp
        self.transactions  = transactions
        self.previous_hash = previous_hash
        self.difficulty    = difficulty
        self.nonce         = nonce

        if hash is not None:
            self.hash = hash
        else:
            self.hash = self.mine_block()

    def _header_data(self) -> dict:
        """
        Datos que entran en el hash del bloque.
        Serialización determinística: siempre produce los mismos bytes
        para el mismo bloque, en cualquier nodo.
        """
        tx_data = [
            tx.to_dict() if hasattr(tx, "to_dict") else tx
            for tx in self.transactions
        ]
        return {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "transactions":  tx_data,
            "previous_hash": self.previous_hash,
            "difficulty":    self.difficulty,
            "nonce":         self.nonce,
        }

    def calculate_hash(self) -> str:
        """
        Hash del bloque usando doble SHA256 y serialización determinística.
        El nonce NO entra en tx_data — solo en el header — así el minado
        solo modifica el nonce sin recalcular las TXs.
        """
        data = _serialize_deterministic(self._header_data())
        return _double_sha256(data)

    def mine_block(self) -> str:
        """Proof of Work: busca nonce tal que el hash empiece con N ceros."""
        target       = "0" * self.difficulty
        hash_attempt = self.calculate_hash()

        while not hash_attempt.startswith(target):
            self.nonce += 1
            hash_attempt = self.calculate_hash()

        return hash_attempt

    def to_dict(self):
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
        from core.transaction import Transaction

        transactions = [
            Transaction.from_dict(tx) if isinstance(tx, dict) else tx
            for tx in data["transactions"]
        ]

        return Block(
            index         = data["index"],
            timestamp     = data["timestamp"],
            transactions  = transactions,
            previous_hash = data["previous_hash"],
            difficulty    = data["difficulty"],
            nonce         = data["nonce"],
            hash          = data["hash"],
        )