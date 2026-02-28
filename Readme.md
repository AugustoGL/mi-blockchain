# 🪙 Mi Blockchain

Red blockchain P2P con Proof of Work, minado automático y transferencias firmadas con ECDSA.

---

## Instalación

Requiere Python 3.10+

```bash
pip install flask cryptography
```

---

## Dificultad de la red

La dificultad se define **una sola vez** al arrancar el bootstrap y queda grabada en el bloque génesis. Todos los nodos que se conecten la heredan automáticamente.

Para cambiarla, editá esta línea en `run_node.py`:

```python
blockchain = Blockchain(difficulty=5)  # ← cambiá este número
```

| Dificultad | Tiempo aprox. por bloque |
|---|---|
| 3 | < 1 segundo |
| 4 | 1-5 segundos |
| 5 | 10-30 segundos |
| 6 | 1-5 minutos |

> ⚠️ Si cambiás la dificultad después de que la red ya está corriendo, tu nodo va a ser incompatible con el resto. La dificultad solo se puede cambiar antes del primer bloque génesis.

---

## Correr en local

Para probar la blockchain en tu propia máquina con múltiples nodos.

**Terminal 1 — nodo bootstrap:**
```bash
python run_node.py 6000 8000
```

**Terminal 2 — segundo nodo:**
```bash
python run_node.py 6001 8001
```

**Terminal 3 — tercer nodo:**
```bash
python run_node.py 6002 8002
```

Los nodos se conectan automáticamente entre sí y empiezan a minar. Podés abrir tantos como quieras incrementando los puertos.

**Verificar que están sincronizados:**
```bash
curl http://localhost:8000/status
curl http://localhost:8001/status
```

**Ver toda la red:**
```bash
curl http://localhost:8000/network
```

---

## Correr el bootstrap

El bootstrap es el nodo central al que se conectan todos. Tiene que estar siempre encendido con una IP/URL accesible.

**Paso 1 — Editá `run_node.py` con tu URL pública:**
```python
# Si usás ngrok:
BOOTSTRAP_URL = "https://abc123.ngrok-free.app"

# Si tenés IP fija:
BOOTSTRAP_URL = "http://190.123.45.67:8000"
```

**Paso 2 — Abrí ngrok** (si no tenés IP fija):
```bash
# Terminal 1 — el nodo
python run_node.py 6000 8000

# Terminal 2 — el túnel
ngrok http 8000
```

Ngrok te da una URL pública. Copiala y pegala en `BOOTSTRAP_URL`.

**Paso 3 — Actualizá `public_url` en `run_node.py`:**
```python
node.public_url = "https://abc123.ngrok-free.app"
```

Esto es importante para que otros nodos sepan cómo contactarte.

> ⚠️ En el plan gratuito de ngrok la URL cambia cada vez que reiniciás el túnel. Tenés que avisarle a tus peers la nueva URL.

---

## Conectarse a un bootstrap

Para unirte a una red existente y empezar a minar.

**Paso 1 — Editá `BOOTSTRAP_URL` en `run_node.py`:**
```python
BOOTSTRAP_URL = "https://abc123.ngrok-free.app"  # URL que te pasó el bootstrap
```

**Paso 2 — Corré el nodo:**
```bash
python run_node.py 6001 8001
```

El nodo se conecta automáticamente al bootstrap, descarga la cadena completa y empieza a minar.

También podés pasar la URL como argumento sin editar el archivo:
```bash
python run_node.py 6001 8001 https://abc123.ngrok-free.app
```

---

## API REST

Cada nodo expone una API en su puerto configurado.

| Método | Endpoint | Descripción |
|---|---|---|
| GET | `/status` | Estado del nodo |
| GET | `/chain` | Blockchain completa |
| GET | `/block/<n>` | Bloque por índice |
| GET | `/mempool` | Transacciones pendientes |
| GET | `/utxos` | Todos los UTXOs |
| GET | `/network` | Todos los nodos conectados |
| GET | `/mining/status` | Estado del minado |
| POST | `/balance` | Balance de una wallet |
| POST | `/transaction` | Enviar transacción firmada |
| POST | `/fund` | Fondear wallet (solo testing) |
| POST | `/mining/stop` | Pausar minado |
| POST | `/mining/start` | Reanudar minado |
| POST | `/connect` | Conectar a un peer manualmente |

---

## Wallets y coins

Cada nodo genera automáticamente una wallet de minero al arrancar. Los coins minados van a esa wallet.

La clave privada se guarda en:
```
node_data_<puerto>/miner_wallet.pem
```

> ⚠️ No pierdas este archivo. Es la única forma de acceder a tus coins.

Para ver cuánto minaste:
```bash
curl http://localhost:8000/mining/status
```

---

## Hacer transferencias

```bash
python test_transferencias.py
```

El script crea wallets de prueba, las fondea y ejecuta transferencias entre los nodos corriendo.

---

## Estructura del proyecto

```
├── run_node.py          ← punto de entrada
├── blockchain.py        ← lógica principal, UTXO set
├── block.py             ← estructura de bloque y PoW
├── transaction.py       ← transacciones ECDSA
├── wallet.py            ← generación y firma de wallets
├── node.py              ← red P2P via HTTP
├── api.py               ← API REST (Flask)
├── miner.py             ← loop de minado automático
├── storage.py           ← persistencia en disco (JSON)
└── test_transferencias.py
```