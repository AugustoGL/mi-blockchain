"""
miner.py — Loop de minado automático con benchmark integrado.
"""

import threading
import time
from test.logger import get_logger


class Miner:

    def __init__(self, blockchain, node, miner_address, poll_interval=0.1):
        self.blockchain    = blockchain
        self.node          = node
        self.miner_address = miner_address if isinstance(miner_address, bytes) \
                             else miner_address.encode()
        self.poll_interval = poll_interval

        self._running = threading.Event()
        self._thread  = None
        self.log      = get_logger(node.port)

        # Estadísticas
        self.blocks_mined    = 0
        self.total_elapsed   = 0.0   # segundos totales minando
        self.total_nonces    = 0     # nonces totales probados

    # ──────────────────────────────────────────────
    # CONTROL
    # ──────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            print("[Miner] Ya está corriendo")
            return
        self._running.set()
        self._thread = threading.Thread(target=self._mining_loop, name="miner", daemon=True)
        self._thread.start()
        print("[Miner] ⛏️  Minado automático iniciado")

    def stop(self):
        self._running.clear()
        print("[Miner] ⏸️  Minado pausado")

    def resume(self):
        if not self._running.is_set():
            self._running.set()
            print("[Miner] ▶️  Minado reanudado")

    @property
    def is_running(self):
        return self._running.is_set()

    # ──────────────────────────────────────────────
    # LOOP PRINCIPAL
    # ──────────────────────────────────────────────

    def _mining_loop(self):
        print(f"[Miner] Minero listo, dirección: "
              f"{self.miner_address[:40].decode(errors='replace')}...")

        while True:
            self._running.wait()

            nonce_before = self.blockchain.get_latest_block().nonce if self.blockchain.chain else 0
            t_start      = time.time()

            success = self.blockchain.mine_pending_transactions(self.miner_address)

            elapsed = time.time() - t_start

            if success:
                new_block = self.blockchain.get_latest_block()
                self.blocks_mined  += 1
                self.total_elapsed += elapsed
                self.total_nonces  += new_block.nonce

                # Hashrate aproximado: nonces / segundos
                hashrate = new_block.nonce / elapsed if elapsed > 0 else 0

                self.log.block_mined_benchmark(new_block, elapsed, hashrate)

                print(f"[Miner] ✅ Bloque #{new_block.index} | "
                      f"nonce={new_block.nonce} | "
                      f"{elapsed:.1f}s | "
                      f"~{hashrate:.0f} H/s | "
                      f"total={self.blocks_mined}")

                self.node.announce_block(new_block)
            else:
                time.sleep(self.poll_interval)

    # ──────────────────────────────────────────────
    # ESTADÍSTICAS Y BENCHMARK
    # ──────────────────────────────────────────────

    def status(self):
        avg_time    = self.total_elapsed / self.blocks_mined if self.blocks_mined else 0
        avg_hashrate = self.total_nonces / self.total_elapsed if self.total_elapsed > 0 else 0

        return {
            "running":       self.is_running,
            "blocks_mined":  self.blocks_mined,
            "chain_length":  len(self.blockchain.chain),
            "pending_txs":   len(self.blockchain.pending_transactions),
            "difficulty":    self.blockchain.difficulty,
            "benchmark": {
                "avg_block_time_sec": round(avg_time, 2),
                "avg_hashrate_hs":    round(avg_hashrate, 1),
                "total_nonces":       self.total_nonces,
                "total_time_sec":     round(self.total_elapsed, 1),
            }
        }