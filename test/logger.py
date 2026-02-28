"""
logger.py — Logging estructurado para la blockchain.

Produce logs en formato JSON, uno por línea, fáciles de parsear
con herramientas como jq, grep, o cualquier sistema de observabilidad.

Ejemplo de output:
  {"ts":1708123456.789,"level":"INFO","node":8000,"event":"block_added","index":42}
  {"ts":1708123456.790,"level":"WARN","node":8000,"event":"peer_strike","strikes":2}

Uso:
    from logger import get_logger
    log = get_logger(port=8000)
    log.block_added(block)
    log.peer_banned(peer_url)
"""

import json
import time
import sys
import threading

_LOCK = threading.Lock()


def _emit(record: dict):
    """Escribe un log JSON en stderr, thread-safe."""
    with _LOCK:
        print(json.dumps(record, separators=(",", ":")), file=sys.stderr, flush=True)


class NodeLogger:

    def __init__(self, port: int):
        self.port = port

    def _base(self, level: str, event: str) -> dict:
        return {"ts": round(time.time(), 3), "level": level, "node": self.port, "event": event}

    # ── Bloques ──────────────────────────────────────────

    def block_added(self, block):
        r = self._base("INFO", "block_added")
        r.update({"index": block.index, "hash": block.hash[:16],
                  "txs": len(block.transactions), "nonce": block.nonce})
        _emit(r)

    def block_invalid(self, reason: str, index: int = None):
        r = self._base("WARN", "block_invalid")
        r.update({"reason": reason})
        if index is not None:
            r["index"] = index
        _emit(r)

    def block_mined(self, block, elapsed_seconds: float):
        r = self._base("INFO", "block_mined")
        r.update({"index": block.index, "hash": block.hash[:16],
                  "nonce": block.nonce, "elapsed": round(elapsed_seconds, 2),
                  "txs": len(block.transactions)})
        _emit(r)

    def block_ignored(self, index: int, reason: str):
        r = self._base("DEBUG", "block_ignored")
        r.update({"index": index, "reason": reason})
        _emit(r)

    # ── Transacciones ────────────────────────────────────

    def tx_accepted(self, tx):
        r = self._base("INFO", "tx_accepted")
        r.update({"tx_id": tx.id[:16], "inputs": len(tx.inputs), "outputs": len(tx.outputs)})
        _emit(r)

    def tx_rejected(self, tx_id: str, reason: str):
        r = self._base("WARN", "tx_rejected")
        r.update({"tx_id": tx_id[:16] if tx_id else "?", "reason": reason})
        _emit(r)

    def tx_expired(self, count: int):
        r = self._base("INFO", "tx_expired")
        r.update({"count": count})
        _emit(r)

    def mempool_full(self):
        _emit(self._base("WARN", "mempool_full"))

    # ── Red ──────────────────────────────────────────────

    def peer_connected(self, peer_url: str):
        r = self._base("INFO", "peer_connected")
        r.update({"peer": peer_url})
        _emit(r)

    def peer_failed(self, peer_url: str):
        r = self._base("WARN", "peer_failed")
        r.update({"peer": peer_url})
        _emit(r)

    def peer_strike(self, peer_url: str, strikes: int, max_strikes: int):
        r = self._base("WARN", "peer_strike")
        r.update({"peer": peer_url, "strikes": strikes, "max": max_strikes})
        _emit(r)

    def peer_banned(self, peer_url: str):
        r = self._base("ERROR", "peer_banned")
        r.update({"peer": peer_url})
        _emit(r)

    def peer_rejected_version(self, peer_url: str, version: str):
        r = self._base("WARN", "peer_rejected_version")
        r.update({"peer": peer_url, "version": version})
        _emit(r)

    def handshake(self, peer_url: str):
        r = self._base("INFO", "handshake")
        r.update({"peer": peer_url})
        _emit(r)

    # ── Cadena ───────────────────────────────────────────

    def chain_adopted(self, length: int, utxos: int, fork_index: int, source: str):
        r = self._base("INFO", "chain_adopted")
        r.update({"length": length, "utxos": utxos, "fork_at": fork_index, "source": source})
        _emit(r)

    def chain_invalid(self, source: str, reason: str):
        r = self._base("WARN", "chain_invalid")
        r.update({"source": source, "reason": reason})
        _emit(r)

    def reorg(self, fork_index: int, txs_recovered: int):
        r = self._base("INFO", "reorg")
        r.update({"fork_at": fork_index, "txs_recovered": txs_recovered})
        _emit(r)

    # ── Minado ───────────────────────────────────────────

    def block_mined_benchmark(self, block, elapsed: float, hashrate: float):
        r = self._base("INFO", "block_mined")
        r.update({"index": block.index, "elapsed": round(elapsed, 2),
                  "nonce": block.nonce, "hashrate": round(hashrate, 1)})
        _emit(r)

    def halving(self, block_index: int, old_reward: float, new_reward: float):
        r = self._base("INFO", "halving")
        r.update({"block": block_index, "old_reward": old_reward, "new_reward": new_reward})
        _emit(r)

    def difficulty_adjusted(self, old: int, new: int, avg_time: float):
        r = self._base("INFO", "difficulty_adjusted")
        r.update({"old": old, "new": new, "avg_block_time": round(avg_time, 1)})
        _emit(r)

    # ── Sistema ──────────────────────────────────────────

    def node_start(self, api_port: int, data_dir: str):
        r = self._base("INFO", "node_start")
        r.update({"api_port": api_port, "data_dir": data_dir})
        _emit(r)

    def rate_limited(self, ip: str):
        r = self._base("WARN", "rate_limited")
        r.update({"ip": ip})
        _emit(r)

    def info(self, event: str, **kwargs):
        r = self._base("INFO", event)
        r.update(kwargs)
        _emit(r)

    def warn(self, event: str, **kwargs):
        r = self._base("WARN", event)
        r.update(kwargs)
        _emit(r)

    def error(self, event: str, **kwargs):
        r = self._base("ERROR", event)
        r.update(kwargs)
        _emit(r)


_loggers: dict = {}

def get_logger(port: int = 0) -> NodeLogger:
    """Devuelve el logger para un puerto dado. Singleton por puerto."""
    if port not in _loggers:
        _loggers[port] = NodeLogger(port)
    return _loggers[port]