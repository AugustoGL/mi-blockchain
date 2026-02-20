"""
miner.py — Loop de minado automático en background.

Corre en un thread separado y mina bloques continuamente.
Cuando encuentra un bloque válido lo anuncia a la red P2P.

Diseño:
  - Un evento threading.Event controla si el loop está activo
  - Entre bloques hay un pequeño sleep para no saturar la CPU
    mientras se espera TXs o se procesa la red
  - Si otro nodo anuncia un bloque más largo, el nodo P2P ya
    actualiza blockchain.chain — el miner simplemente continúa
    minando sobre la nueva punta de la cadena
"""

import threading
import time


class Miner:

    def __init__(self, blockchain, node, miner_address, poll_interval=0.1):
        """
        blockchain     — instancia de Blockchain compartida con la API y el nodo P2P
        node           — instancia de Node para anunciar bloques minados
        miner_address  — bytes con la clave pública del minero (recibe el coinbase)
        poll_interval  — segundos de espera entre intentos cuando la cadena cambia
        """
        self.blockchain    = blockchain
        self.node          = node
        self.miner_address = miner_address if isinstance(miner_address, bytes) \
                             else miner_address.encode()
        self.poll_interval = poll_interval

        self._running = threading.Event()   # set → minando, clear → pausado
        self._thread  = None

        self.blocks_mined = 0   # contador para estadísticas

    # ──────────────────────────────────────────────
    # CONTROL
    # ──────────────────────────────────────────────

    def start(self):
        """Arranca el loop de minado en un thread daemon."""
        if self._thread and self._thread.is_alive():
            print("[Miner] Ya está corriendo")
            return

        self._running.set()
        self._thread = threading.Thread(
            target=self._mining_loop,
            name="miner",
            daemon=True   # muere con el proceso principal
        )
        self._thread.start()
        print(f"[Miner] ⛏️  Minado automático iniciado")

    def stop(self):
        """Pausa el minado. El bloque en curso termina antes de detenerse."""
        self._running.clear()
        print("[Miner] ⏸️  Minado pausado")

    def resume(self):
        """Reanuda el minado si estaba pausado."""
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
        """
        Loop infinito de minado.

        Por qué funciona bien con la sincronización P2P:
          - blockchain.chain es la misma instancia que usa el nodo P2P
          - Cuando _handle_enviar_cadena adopta una cadena más larga,
            actualiza blockchain.chain directamente
          - mine_pending_transactions siempre trabaja sobre
            blockchain.get_latest_block(), que apunta a la punta actual
          - Si llega un bloque externo mientras estamos minando,
            el siguiente intento de mine_pending_transactions fallará
            (el previous_hash ya no coincide) y simplemente reintentamos
            sobre la nueva punta — sin inconsistencias
        """
        print(f"[Miner] Minero listo, dirección: "
              f"{self.miner_address[:40].decode(errors='replace')}...")

        while True:
            # Respetar la pausa
            self._running.wait()   # bloquea aquí si está pausado

            chain_len_before = len(self.blockchain.chain)

            # Intentar minar
            success = self.blockchain.mine_pending_transactions(self.miner_address)

            if success:
                new_block = self.blockchain.get_latest_block()
                self.blocks_mined += 1
                print(f"[Miner] ✅ Bloque #{new_block.index} minado "
                      f"(nonce={new_block.nonce}, "
                      f"txs={len(new_block.transactions)}, "
                      f"total minados={self.blocks_mined})")

                # Anunciar a la red — esto es thread-safe porque
                # node.broadcast usa su propio lock interno
                self.node.announce_block(new_block)

            else:
                # mine_pending_transactions devuelve False si la cadena
                # cambió por debajo (bloque externo llegó mientras minábamos)
                # o si hubo algún error de validación.
                # Esperamos un momento y reintentamos sobre la nueva punta.
                time.sleep(self.poll_interval)

    # ──────────────────────────────────────────────
    # ESTADÍSTICAS
    # ──────────────────────────────────────────────

    def status(self):
        return {
            "running":      self.is_running,
            "blocks_mined": self.blocks_mined,
            "chain_length": len(self.blockchain.chain),
            "pending_txs":  len(self.blockchain.pending_transactions),
        }