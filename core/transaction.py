import hashlib
import json
import time as _time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed


def _double_sha256(data: bytes) -> bytes:
    """
    Hash doble SHA256 como Bitcoin.
    Protege contra ataques de extensión de longitud (length extension attacks).
    SHA256(SHA256(data))
    """
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _serialize_deterministic(data: dict) -> bytes:
    """
    Serialización determinística via JSON con sort_keys=True.
    Garantiza que el mismo dict siempre produce los mismos bytes,
    independientemente del orden en que se crearon las claves.
    Sin esto, dos nodos podrían calcular IDs distintos para la misma TX.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Transaction:
    def __init__(self, inputs, outputs, timestamp=None):
        self.inputs    = inputs
        self.outputs   = outputs
        self.timestamp = timestamp or _time.time()
        self.id        = self.calculate_id()

    def _signable_data(self) -> dict:
        """
        Datos que entran en la firma y en el ID.
        NO incluye las firmas — así una firma modificada no cambia el ID.
        Esto protege contra transaction malleability.
        Incluye timestamp para que dos TXs idénticas en momentos distintos
        tengan IDs distintos.
        """
        return {
            "inputs": [
                {"tx_id": i.tx_id, "output_index": i.output_index}
                for i in self.inputs
            ],
            "outputs": [
                {
                    "amount": o.amount,
                    "recipient": o.recipient_public_key.decode()
                    if isinstance(o.recipient_public_key, bytes)
                    else o.recipient_public_key
                }
                for o in self.outputs
            ],
            "timestamp": self.timestamp,
        }

    def calculate_id(self) -> str:
        """
        ID de la TX = hex del doble SHA256 de los datos serializados.
        No incluye firmas → malleability protegida.
        Serialización determinística → IDs consistentes entre nodos.
        """
        data  = _serialize_deterministic(self._signable_data())
        return _double_sha256(data).hex()

    def hash_for_signature(self) -> bytes:
        """
        Hash que firman los inputs.
        Igual que calculate_id pero devuelve bytes crudos para ECDSA.
        """
        data = _serialize_deterministic(self._signable_data())
        return _double_sha256(data)

    def sign(self, private_key):
        tx_hash = self.hash_for_signature()
        for i in self.inputs:
            i.sign(tx_hash, private_key)

    def is_coinbase(self):
        return len(self.inputs) == 0

    def verify(self, utxo_set):
        if self.is_coinbase():
            return True, 0

        tx_hash    = self.hash_for_signature()
        input_sum  = 0
        output_sum = sum(o.amount for o in self.outputs)

        # Verificar que no haya overflow/underflow en outputs
        if output_sum < 0:
            raise Exception("Output negativo")

        for inp in self.inputs:
            key = (inp.tx_id, inp.output_index)

            if key not in utxo_set:
                raise Exception("UTXO inexistente")

            utxo = utxo_set[key]

            if utxo.amount < 0:
                raise Exception("UTXO con monto negativo")

            input_sum += utxo.amount

            # Verificar firma ECDSA con doble SHA256
            public_key = serialization.load_pem_public_key(
                utxo.recipient_public_key
                if isinstance(utxo.recipient_public_key, bytes)
                else utxo.recipient_public_key.encode()
            )

            # ECDSA con prehashed=True porque ya aplicamos doble SHA256
            public_key.verify(
                inp.signature,
                tx_hash,
                ec.ECDSA(Prehashed(hashes.SHA256()))
            )

        if input_sum < output_sum:
            raise Exception("Creación de dinero: inputs < outputs")

        return True, input_sum - output_sum

    def to_dict(self):
        return {
            "id":        self.id,
            "timestamp": self.timestamp,
            "inputs":    [i.to_dict() for i in self.inputs],
            "outputs":   [o.to_dict() for o in self.outputs],
        }

    @staticmethod
    def from_dict(data):
        if isinstance(data, Transaction):
            return data

        inputs  = [TxInput.from_dict(i)  for i in data.get("inputs",  [])]
        outputs = [TxOutput.from_dict(o) for o in data.get("outputs", [])]
        tx      = Transaction(inputs=inputs, outputs=outputs, timestamp=data.get("timestamp"))
        tx.id   = data["id"]
        return tx


class TxInput:
    def __init__(self, tx_id, output_index):
        self.tx_id        = tx_id
        self.output_index = output_index
        self.signature    = None

    def sign(self, tx_hash: bytes, private_key):
        """Firma con ECDSA. tx_hash ya es el doble SHA256, usamos Prehashed."""
        self.signature = private_key.sign(
            tx_hash,
            ec.ECDSA(Prehashed(hashes.SHA256()))
        )

    def to_dict(self):
        return {
            "tx_id":        self.tx_id,
            "output_index": self.output_index,
            "signature":    self.signature.hex() if self.signature else None,
        }

    @staticmethod
    def from_dict(data):
        inp = TxInput(tx_id=data["tx_id"], output_index=data["output_index"])
        if data.get("signature"):
            inp.signature = bytes.fromhex(data["signature"])
        return inp


class TxOutput:
    def __init__(self, amount, recipient_public_key_pem):
        if amount < 0:
            raise ValueError(f"Monto negativo no permitido: {amount}")
        self.amount              = amount
        self.recipient_public_key = recipient_public_key_pem

    def to_dict(self):
        pk = self.recipient_public_key
        if isinstance(pk, bytes):
            pk = pk.decode()
        return {
            "amount":              self.amount,
            "recipient_public_key": pk,
        }

    @staticmethod
    def from_dict(data):
        pk = data["recipient_public_key"]
        if isinstance(pk, str):
            pk = pk.encode()
        return TxOutput(amount=data["amount"], recipient_public_key_pem=pk)