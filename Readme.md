# 🪙 Mi Blockchain

Implementación propia de una blockchain estilo Bitcoin, hecha desde cero en Python
para entender a fondo cómo funciona una red de este tipo por dentro: criptografía,
modelo UTXO, consenso por Proof of Work y sincronización P2P entre nodos.

No es un clon simplificado con atajos — usa la misma curva criptográfica que
Bitcoin (SECP256K1) y el mismo modelo de transacciones (UTXO), aunque con menos
piezas que una red de producción real (ver sección de alcance más abajo).

## Qué implementa

**Criptografía**
- Doble SHA-256 (`SHA256(SHA256(x))`) para hashes de bloques y transacciones
- Firmas ECDSA sobre curva SECP256K1 — la misma que usa Bitcoin
- Serialización determinística (JSON con `sort_keys`) para que todos los nodos
  calculen exactamente el mismo hash a partir de los mismos datos

**Modelo UTXO**
- Cada wallet arma sus transacciones seleccionando UTXOs disponibles y
  calculando el cambio, igual que en Bitcoin real (no es un simple balance
  por cuenta)
- Protección contra *transaction malleability*: la firma no forma parte
  del ID de la transacción
- Prevención de doble gasto bloqueando los UTXOs que ya están en la mempool

**Consenso (Proof of Work)**
- Minado por fuerza bruta del nonce hasta cumplir la dificultad
- Ajuste automático de dificultad cada 10 bloques según el tiempo real vs.
  el tiempo objetivo, limitado a un factor 2x por ajuste (igual que Bitcoin)
- *Halving* de la recompensa cada 210 bloques, con supply máximo de 21,000,000
- Selección de transacciones a minar priorizando las de mayor fee

**Red P2P**
- Handshake, descubrimiento y propagación automática de peers a toda la red
- Sincronización de cadena: un nodo adopta la cadena más larga válida que
  reciba de sus peers
- *Reorg*: al adoptar una cadena nueva, las transacciones de los bloques
  descartados vuelven a la mempool en vez de perderse
- Persistencia en disco (cadena, UTXO set, mempool y peers) — un nodo puede
  reiniciarse sin perder su estado

## Alcance (qué NO tiene, a propósito)

Para mantener el proyecto enfocado en aprender los fundamentos, quedaron
afuera piezas que sí tiene Bitcoin real:

- Merkle trees (acá los hashes de las transacciones van directo al header del bloque)
- Un lenguaje de scripting en los outputs (Bitcoin Script); los outputs acá
  son simples: monto + clave pública destino
- Un protocolo de difusión tipo *gossip*; la propagación es HTTP directo entre peers conocidos

## Wallets

Cada nodo genera automáticamente una wallet de minero (clave ECDSA real) al
arrancar, y la clave privada se guarda en `node_data_<puerto>/miner_wallet.pem`.
Los coins minados van a esa wallet y quedan reflejados en el UTXO set real de
la cadena — no es un balance simulado.

## Stack

Python 3.10+, `flask`, `cryptography` (ECDSA / SECP256K1).

## Instalación

```bash
pip install flask cryptography
```

## Correr en local (varios nodos en tu propia máquina)

```bash
# Terminal 1 — nodo bootstrap
python run_node.py 6000 8000

# Terminal 2 — segundo nodo
python run_node.py 6001 8001

# Terminal 3 — tercer nodo
python run_node.py 6002 8002
```

Los nodos se conectan automáticamente entre sí y empiezan a minar.

```bash
curl http://localhost:8000/status     # ver estado de un nodo
curl http://localhost:8000/network    # ver toda la red
```

## Correr con nodos en máquinas distintas

El bootstrap es el nodo central al que se conectan los demás; necesita una
URL pública accesible (IP fija o un túnel como [ngrok](https://ngrok.com)).

```bash
# Nodo bootstrap
python run_node.py 6000 8000
ngrok http 8000   # te da una URL pública

# Nodo que se une a la red
python run_node.py 6001 8001 https://<tu-url-de-ngrok>
```

## Dificultad de la red

Se define una única vez al crear el bloque génesis, y todos los nodos que se
conecten la heredan automáticamente. Se ajusta sola después según el tiempo
real de minado (ver `calculate_next_difficulty` en `core/blockchain.py`).

| Dificultad | Tiempo aprox. por bloque |
|---|---|
| 3 | < 1 segundo |
| 4 | 1–5 segundos |
| 5 | 10–30 segundos |
| 6 | 1–5 minutos |

## API REST

Cada nodo expone su propia API en el puerto configurado.

| Método | Endpoint | Descripción |
|---|---|---|
| GET | `/status` | Estado del nodo |
| GET | `/chain` | Blockchain completa |
| GET | `/block/<n>` | Bloque por índice |
| GET | `/mempool` | Transacciones pendientes |
| GET | `/utxos` | Todos los UTXOs |
| GET | `/network` | Todos los nodos conectados |
| GET | `/mining/status` | Estado del minado (incluye benchmark de hashrate) |
| POST | `/balance` | Balance de una wallet |
| POST | `/transaction` | Enviar transacción firmada |
| POST | `/fund` | Fondear wallet (solo testing) |
| POST | `/mining/stop` / `/mining/start` | Pausar / reanudar minado |
| POST | `/connect` | Conectar a un peer manualmente |

## Hacer transferencias de prueba

```bash
python test/test.py
```

Crea wallets de prueba, las fondea y ejecuta transferencias entre los nodos
corriendo.

## Estructura del proyecto

```
├── run_node.py           ← punto de entrada
├── core/
│   ├── block.py           ← estructura de bloque y Proof of Work
│   ├── blockchain.py       ← lógica principal: UTXO set, consenso, validación
│   ├── transaction.py      ← transacciones y firmas ECDSA
│   └── wallet.py           ← generación de wallets, armado de transacciones
├── mining/
│   └── miner.py            ← loop de minado automático con benchmark
├── network/
│   ├── node.py              ← red P2P: peers, sync, reorg, broadcast
│   ├── api.py                ← API REST (Flask)
│   └── protocol.py
├── storage/
│   └── storage.py            ← persistencia en disco (JSON)
└── test/
    ├── test.py                ← script de transferencias de prueba
    └── logger.py
```
