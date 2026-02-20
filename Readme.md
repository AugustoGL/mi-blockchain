# 🪙 Mi Blockchain — Instrucciones para minar

## Requisitos

```bash
pip install flask cryptography
```

---

## Si sos VOS (el que tiene el bootstrap)

### Paso 1 — Editá tu IP pública en run_node.py

Abrí `run_node.py` y cambiá esta línea con tu IP pública
(la podés ver en https://whatismyip.com):

```python
BOOTSTRAP_HOST = "190.123.45.67"   # ← tu IP pública acá
```

### Paso 2 — Abrí el puerto en tu router

En tu router hacé **port forwarding** del puerto **6000 TCP**
hacia tu PC (IP local, por ejemplo 192.168.1.100).

### Paso 3 — Levantá el nodo bootstrap

```bash
python run_node.py 6000 8000
```

Dejalo corriendo. Este es el nodo central al que se conectan todos.

---

## Si sos el AMIGO (querés minar)

### Paso 1 — Editá run_node.py con la IP del bootstrap

Abrí `run_node.py` y fijate que BOOTSTRAP_HOST tenga la IP
pública del que te pasó el código:

```python
BOOTSTRAP_HOST = "190.123.45.67"   # IP del que te pasó esto
BOOTSTRAP_P2P  = 6000
```

### Paso 2 — Levantá tu nodo

```bash
python run_node.py 6001 8001
```

Listo. El nodo se conecta solo al bootstrap, descarga la cadena
y empieza a minar automáticamente.

---

## Comandos útiles

Ver estado del nodo:
```bash
curl http://localhost:8000/status
```

Ver la blockchain:
```bash
curl http://localhost:8000/chain
```

Ver tus coins minados (reemplazá PORT por tu puerto API):
```bash
curl http://localhost:8000/mining/status
```

Ver balance de una wallet:
```bash
curl -X POST http://localhost:8000/balance \
  -H "Content-Type: application/json" \
  -d "{\"address\": \"TU_CLAVE_PUBLICA_PEM\"}"
```

---

## Varios nodos en la misma PC

```bash
# Terminal 1
python run_node.py 6000 8000

# Terminal 2
python run_node.py 6001 8001

# Terminal 3
python run_node.py 6002 8002
```

Cada nodo mina en paralelo y se sincroniza con los demás.

---

## Cómo se ganan coins

Cada vez que tu nodo mina un bloque recibe **50 coins** (coinbase).
Los coins quedan en la wallet guardada en:

```
node_data_6000/miner_wallet.pem   ← clave privada, no la pierdas
```

---

## Hacer una transferencia

Usá el script incluido:

```bash
python test_transferencias.py
```

O manualmente via API:

```bash
# 1. Ver UTXOs disponibles
curl http://localhost:8000/utxos

# 2. Enviar TX (creada y firmada con wallet.py)
curl -X POST http://localhost:8000/transaction \
  -H "Content-Type: application/json" \
  -d @mi_transaccion.json
```

---

## Topología de red recomendada

```
         [Bootstrap :6000]
        /        |        \
   [6001]      [6002]    [6003]  ← amigos
```

Una vez conectados al bootstrap, los nodos se descubren
entre sí automáticamente y el bootstrap puede apagarse
sin que la red se caiga.