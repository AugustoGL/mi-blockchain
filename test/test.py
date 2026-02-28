"""
test.py — Tests unitarios y de ataque para la blockchain.

Corre con:
    python3 test/test.py
    python3 test/test.py -v   (verbose)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import unittest
import tempfile

# Setear DATA_DIR ANTES de importar cualquier módulo que use storage.
from storage import storage as storage_module
_TMP = tempfile.mkdtemp()
storage_module.DATA_DIR = _TMP

from core.blockchain import Blockchain, get_mining_reward, HALVING_INTERVAL, INITIAL_REWARD
from core.block import Block
from core.transaction import Transaction, TxInput, TxOutput, _double_sha256
from core.wallet import Wallet


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def make_blockchain(difficulty=1):
    for f in ["chain.json", "utxo_set.json", "mempool.json"]:
        path = os.path.join(_TMP, f)
        if os.path.exists(path):
            os.remove(path)
    return Blockchain(difficulty=difficulty)


def funded_wallet(bc: Blockchain, amount=100):
    w   = Wallet()
    out = TxOutput(amount=amount, recipient_public_key_pem=w.address())
    tx  = Transaction(inputs=[], outputs=[out])
    bc.utxo_set[(tx.id, 0)] = out
    return w, tx


# ══════════════════════════════════════════════════════════════════
# 1. TESTS DE BLOQUE
# ══════════════════════════════════════════════════════════════════

class TestBlock(unittest.TestCase):

    def test_hash_correcto(self):
        bc    = make_blockchain()
        block = bc.chain[0]
        self.assertEqual(block.hash, block.calculate_hash())

    def test_pow_cumple_dificultad(self):
        bc = make_blockchain(difficulty=2)
        bc.mine_pending_transactions(b"miner")
        block = bc.get_latest_block()
        self.assertTrue(block.hash.startswith("00"))

    def test_modificar_bloque_invalida_hash(self):
        bc    = make_blockchain()
        block = bc.chain[0]
        block.index = 999
        self.assertNotEqual(block.hash, block.calculate_hash())

    def test_serializacion_deterministica(self):
        bc    = make_blockchain()
        block = bc.chain[0]
        self.assertEqual(block.calculate_hash(), block.calculate_hash())


# ══════════════════════════════════════════════════════════════════
# 2. TESTS DE TRANSACCIÓN
# ══════════════════════════════════════════════════════════════════

class TestTransaction(unittest.TestCase):

    def test_tx_id_no_incluye_firma(self):
        bc       = make_blockchain()
        w, ftx   = funded_wallet(bc)
        inp      = TxInput(tx_id=ftx.id, output_index=0)
        tx       = Transaction(inputs=[inp], outputs=[TxOutput(1, w.address())])
        id_antes = tx.id
        tx_hash  = tx.hash_for_signature()
        inp.sign(tx_hash, w.private_key)
        self.assertEqual(id_antes, tx.id)

    def test_firma_valida(self):
        bc     = make_blockchain()
        w, ftx = funded_wallet(bc, amount=100)
        w2     = Wallet()
        inp    = TxInput(tx_id=ftx.id, output_index=0)
        tx     = Transaction(
            inputs  = [inp],
            outputs = [TxOutput(50, w2.address()), TxOutput(50, w.address())]
        )
        tx_hash = tx.hash_for_signature()
        inp.sign(tx_hash, w.private_key)
        valid, fee = tx.verify(bc.utxo_set)
        self.assertTrue(valid)
        self.assertEqual(fee, 0)

    def test_firma_invalida_falla(self):
        bc      = make_blockchain()
        w, ftx  = funded_wallet(bc, amount=100)
        w_malo  = Wallet()
        inp     = TxInput(tx_id=ftx.id, output_index=0)
        tx      = Transaction(inputs=[inp], outputs=[TxOutput(100, w.address())])
        tx_hash = tx.hash_for_signature()
        inp.sign(tx_hash, w_malo.private_key)
        with self.assertRaises(Exception):
            tx.verify(bc.utxo_set)

    def test_doble_gasto_rechazado(self):
        bc     = make_blockchain()
        w, ftx = funded_wallet(bc, amount=100)
        w2     = Wallet()

        inp1     = TxInput(tx_id=ftx.id, output_index=0)
        tx1      = Transaction(inputs=[inp1], outputs=[TxOutput(100, w2.address())])
        tx1_hash = tx1.hash_for_signature()
        inp1.sign(tx1_hash, w.private_key)
        self.assertTrue(bc.add_transaction(tx1))

        inp2     = TxInput(tx_id=ftx.id, output_index=0)
        tx2      = Transaction(inputs=[inp2], outputs=[TxOutput(100, w2.address())])
        tx2_hash = tx2.hash_for_signature()
        inp2.sign(tx2_hash, w.private_key)
        self.assertFalse(bc.add_transaction(tx2))

    def test_crear_dinero_rechazado(self):
        bc      = make_blockchain()
        w, ftx  = funded_wallet(bc, amount=100)
        w2      = Wallet()
        inp     = TxInput(tx_id=ftx.id, output_index=0)
        tx      = Transaction(inputs=[inp], outputs=[TxOutput(9999, w2.address())])
        tx_hash = tx.hash_for_signature()
        inp.sign(tx_hash, w.private_key)
        with self.assertRaises(Exception):
            tx.verify(bc.utxo_set)

    def test_utxo_inexistente_rechazado(self):
        bc      = make_blockchain()
        w       = Wallet()
        inp     = TxInput(tx_id="utxo_falso", output_index=0)
        tx      = Transaction(inputs=[inp], outputs=[TxOutput(10, w.address())])
        tx_hash = tx.hash_for_signature()
        inp.sign(tx_hash, w.private_key)
        with self.assertRaises(Exception):
            tx.verify(bc.utxo_set)

    def test_monto_negativo_rechazado(self):
        w = Wallet()
        with self.assertRaises(ValueError):
            TxOutput(amount=-1, recipient_public_key_pem=w.address())

    def test_double_sha256(self):
        import hashlib
        data   = b"test data"
        manual = hashlib.sha256(hashlib.sha256(data).digest()).digest()
        self.assertEqual(_double_sha256(data), manual)


# ══════════════════════════════════════════════════════════════════
# 3. TESTS DE CADENA
# ══════════════════════════════════════════════════════════════════

class TestBlockchain(unittest.TestCase):

    def test_genesis_valido(self):
        bc = make_blockchain()
        self.assertEqual(len(bc.chain), 1)
        self.assertTrue(bc.validate_chain())

    def test_minar_agrega_bloque(self):
        bc = make_blockchain(difficulty=1)
        bc.mine_pending_transactions(b"miner")
        self.assertEqual(len(bc.chain), 2)

    def test_cadena_valida_tras_minado(self):
        bc = make_blockchain(difficulty=1)
        for _ in range(3):
            bc.mine_pending_transactions(b"miner")
        self.assertTrue(bc.validate_chain())

    def test_tamper_tx_invalida_cadena(self):
        bc = make_blockchain(difficulty=1)
        bc.mine_pending_transactions(b"miner")
        bc.chain[1].transactions[0].outputs[0].amount = 999999
        self.assertFalse(bc.validate_chain())

    def test_tx_index_correcto(self):
        bc    = make_blockchain(difficulty=1)
        bc.mine_pending_transactions(b"miner")
        block = bc.chain[1]
        tx_id = block.transactions[0].id
        tx, bi = bc.get_transaction(tx_id)
        self.assertIsNotNone(tx)
        self.assertEqual(bi, 1)

    def test_tx_inexistente_devuelve_none(self):
        bc     = make_blockchain()
        tx, bi = bc.get_transaction("tx_que_no_existe")
        self.assertIsNone(tx)
        self.assertIsNone(bi)


# ══════════════════════════════════════════════════════════════════
# 4. TESTS DE POLÍTICA MONETARIA
# ══════════════════════════════════════════════════════════════════

class TestEmision(unittest.TestCase):

    def test_recompensa_inicial(self):
        self.assertEqual(get_mining_reward(0), INITIAL_REWARD)

    def test_halving(self):
        reward_antes   = get_mining_reward(HALVING_INTERVAL - 1)
        reward_despues = get_mining_reward(HALVING_INTERVAL)
        self.assertEqual(reward_despues, reward_antes / 2)

    def test_recompensa_nunca_negativa(self):
        for i in range(0, HALVING_INTERVAL * 100, HALVING_INTERVAL):
            self.assertGreaterEqual(get_mining_reward(i), 0)


# ══════════════════════════════════════════════════════════════════
# 5. TESTS DE ATAQUE
# ══════════════════════════════════════════════════════════════════

class TestAtaques(unittest.TestCase):

    def test_timestamp_futuro_rechazado(self):
        bc           = make_blockchain(difficulty=1)
        bloque_falso = Block(
            index         = 1,
            timestamp     = time.time() + 36000,
            transactions  = [Transaction([], [TxOutput(50, b"miner")])],
            previous_hash = bc.chain[0].hash,
            difficulty    = 1,
        )
        self.assertFalse(bc.add_block(bloque_falso))

    def test_dificultad_baja_rechazada(self):
        bc           = make_blockchain(difficulty=2)
        bloque_facil = Block(
            index         = 1,
            timestamp     = time.time(),
            transactions  = [Transaction([], [TxOutput(50, b"miner")])],
            previous_hash = bc.chain[0].hash,
            difficulty    = 1,
        )
        self.assertFalse(bc.add_block(bloque_facil))

    def test_bloque_sin_coinbase_rechazado(self):
        bc           = make_blockchain(difficulty=1)
        bloque_vacio = Block(
            index         = 1,
            timestamp     = time.time(),
            transactions  = [],
            previous_hash = bc.chain[0].hash,
            difficulty    = 1,
        )
        self.assertFalse(bc.add_block(bloque_vacio))

    def test_cadena_alternativa_corta_rechazada(self):
        bc = make_blockchain(difficulty=1)
        for _ in range(5):
            bc.mine_pending_transactions(b"miner")
        cadena_corta = bc.chain[:3]
        self.assertLess(len(cadena_corta), len(bc.chain))

    def test_mempool_limite(self):
        from core.blockchain import MAX_MEMPOOL_SIZE
        import hashlib
        bc = make_blockchain()
        w  = Wallet()

        for i in range(MAX_MEMPOOL_SIZE + 5):
            out        = TxOutput(1, w.address())
            fake_tx_id = hashlib.sha256(f"fake-{i}".encode()).hexdigest()
            bc.utxo_set[(fake_tx_id, 0)] = out

        w2        = Wallet()
        aceptadas = 0
        for i in range(MAX_MEMPOOL_SIZE + 5):
            fake_tx_id = hashlib.sha256(f"fake-{i}".encode()).hexdigest()
            inp     = TxInput(tx_id=fake_tx_id, output_index=0)
            tx      = Transaction(inputs=[inp], outputs=[TxOutput(1, w2.address())])
            tx_hash = tx.hash_for_signature()
            inp.sign(tx_hash, w.private_key)
            if bc.add_transaction(tx):
                aceptadas += 1

        self.assertLessEqual(aceptadas, MAX_MEMPOOL_SIZE)


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    verbose = "-v" in sys.argv
    loader  = unittest.TestLoader()
    suite   = unittest.TestSuite()

    for cls in [TestBlock, TestTransaction, TestBlockchain, TestEmision, TestAtaques]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
    result = runner.run(suite)

    sys.exit(0 if result.wasSuccessful() else 1)