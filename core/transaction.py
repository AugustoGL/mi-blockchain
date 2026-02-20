import hashlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


class Transaction:
    def __init__(self, inputs, outputs):
        self.inputs = inputs
        self.outputs = outputs
        self.id = self.calculate_id()

    def calculate_id(self):
        s = ""
        for i in self.inputs:
            s += f"{i.tx_id}{i.output_index}"
        for o in self.outputs:
            s += f"{o.amount}{o.recipient_public_key}"
        return hashlib.sha256(s.encode()).hexdigest()

    def hash_for_signature(self) -> bytes:
        s = ""
        for i in self.inputs:
            s += f"{i.tx_id}{i.output_index}"
        for o in self.outputs:
            s += f"{o.amount}{o.recipient_public_key}"
        return hashlib.sha256(s.encode()).digest()

    def sign(self, private_key):
        tx_hash = self.hash_for_signature()
        for i in self.inputs:
            i.sign(tx_hash, private_key)

    def is_coinbase(self):
        return len(self.inputs) == 0

    def verify(self, utxo_set):
        if self.is_coinbase():
            return True, 0

        tx_hash = self.hash_for_signature()

        input_sum = 0
        output_sum = sum(o.amount for o in self.outputs)

        for inp in self.inputs:
            key = (inp.tx_id, inp.output_index)

            if key not in utxo_set:
                raise Exception("UTXO inexistente")

            utxo = utxo_set[key]
            input_sum += utxo.amount

            public_key = serialization.load_pem_public_key(
                utxo.recipient_public_key
            )

            public_key.verify(
                inp.signature,
                tx_hash,
                ec.ECDSA(hashes.SHA256())
            )

        if input_sum < output_sum:
            raise Exception("Creación de dinero")

        return True, input_sum - output_sum

    def to_dict(self):
        return {
            "id": self.id,
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
        }

    @staticmethod
    def from_dict(data):
        # Si ya es un objeto Transaction, devolverlo tal cual
        if isinstance(data, Transaction):
            return data

        inputs = [
            TxInput.from_dict(i) for i in data.get("inputs", [])
        ]
        outputs = [
            TxOutput.from_dict(o) for o in data.get("outputs", [])
        ]
        tx = Transaction(inputs=inputs, outputs=outputs)
        tx.id = data["id"]
        return tx


class TxInput:
    def __init__(self, tx_id, output_index):
        self.tx_id = tx_id
        self.output_index = output_index
        self.signature = None

    def sign(self, tx_hash: bytes, private_key):
        self.signature = private_key.sign(
            tx_hash,
            ec.ECDSA(hashes.SHA256())
        )

    def to_dict(self):
        return {
            "tx_id": self.tx_id,
            "output_index": self.output_index,
            "signature": self.signature.hex() if self.signature else None
        }

    @staticmethod
    def from_dict(data):
        inp = TxInput(tx_id=data["tx_id"], output_index=data["output_index"])
        if data.get("signature"):
            inp.signature = bytes.fromhex(data["signature"])
        return inp

    def verify(self, recipient_public_key):
        public_key = serialization.load_pem_public_key(recipient_public_key)
        public_key.verify(
            self.signature,
            self.tx_id.encode(),
            ec.ECDSA(hashes.SHA256())
        )
        return True


class TxOutput:
    def __init__(self, amount, recipient_public_key_pem):
        self.amount = amount
        self.recipient_public_key = recipient_public_key_pem

    def to_dict(self):
        pk = self.recipient_public_key
        if isinstance(pk, bytes):
            pk = pk.decode()
        return {
            "amount": self.amount,
            "recipient_public_key": pk
        }

    @staticmethod
    def from_dict(data):
        pk = data["recipient_public_key"]
        if isinstance(pk, str):
            pk = pk.encode()
        return TxOutput(amount=data["amount"], recipient_public_key_pem=pk)