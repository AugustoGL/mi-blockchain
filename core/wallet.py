from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from core.transaction import Transaction, TxInput, TxOutput


class Wallet:
    def __init__(self, key_file=None):
        if key_file:
            self._load(key_file)
        else:
            self.private_key = ec.generate_private_key(ec.SECP256K1())
            self.public_key  = self.private_key.public_key()

    def save(self, key_file):
        """Guarda la clave privada en un archivo PEM (sin password)."""
        pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(key_file, "wb") as f:
            f.write(pem)

    def _load(self, key_file):
        """Carga la clave privada desde un archivo PEM."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        with open(key_file, "rb") as f:
            self.private_key = load_pem_private_key(f.read(), password=None)
        self.public_key = self.private_key.public_key()

    def address(self):
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def get_balance(self, blockchain):
        balance = 0
        for key, utxo in blockchain.utxo_set.items():
            if utxo.recipient_public_key == self.address():
                balance += utxo.amount
        return balance

    def select_utxos(self, blockchain, amount_needed):
        locked   = blockchain.get_locked_utxos()
        selected = []
        total    = 0

        for (txid, idx), utxo in blockchain.utxo_set.items():
            if utxo.recipient_public_key != self.address():
                continue
            if (txid, idx) in locked:
                continue

            selected.append((txid, idx, utxo))
            total += utxo.amount

            if total >= amount_needed:
                break

        return selected, total

    def create_transaction(self, blockchain, receiver_public_key_pem, amount, fee):
        total_needed = amount + fee
        selected_utxos, total_available = self.select_utxos(blockchain, total_needed)

        if total_available < total_needed:
            raise Exception(
                f"Fondos insuficientes: disponible={total_available}, necesario={total_needed}"
            )

        inputs = []
        for txid, out_idx, _utxo in selected_utxos:
            inputs.append(TxInput(tx_id=txid, output_index=out_idx))

        outputs = [TxOutput(amount=amount, recipient_public_key_pem=receiver_public_key_pem)]

        change = total_available - total_needed
        if change > 0:
            outputs.append(TxOutput(amount=change, recipient_public_key_pem=self.address()))

        tx      = Transaction(inputs=inputs, outputs=outputs)
        tx_hash = tx.hash_for_signature()
        for tx_input in tx.inputs:
            tx_input.sign(tx_hash, self.private_key)

        return tx

    def get_utxos(self, blockchain):
        my_pubkey = self.address()
        utxos     = []
        for (tx_id, out_idx), utxo in blockchain.utxo_set.items():
            if utxo.recipient_public_key == my_pubkey:
                utxos.append((tx_id, out_idx, utxo))
        return utxos