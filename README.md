# Smart Gym - Checkpoint 05 (IoT & IoB)

Projeto desenvolvido para a disciplina de **Physical Computing / IoT** (Turma 3ESPZ - FIAP).

---

## Estrutura do Projeto

- `esp32/smart_station_rfid.ino`: Firmware ESP32 com leitor RFID MFRC522, LEDs de status, buzzer e publicador MQTT.
- `esp32/diagram.json`: Esquema elétrico e conexões para teste/simulação no Wokwi.
- `vision/exercise_tracker.py`: Script Python com YOLOv8-Pose para rastreamento articular, detecção da massa preta (celular como peso) na mão, cálculo de ângulo do cotovelo, contagem de repetições e detecção de fadiga.
- `dashboard/app.py`: Backend Flask com cliente MQTT e Server-Sent Events (SSE) para atualização em tempo real sem refresh.
- `dashboard/templates/index.html`: Interface web moderna com TailwindCSS exibindo status da estação, aluno logado, repetições, ângulo em tempo real e histórico de séries.
- `simulator/esp32_simulator.py`: Utilitário de linha de comando para simular leituras de tags RFID e eventos do ESP32.
- `requirements.txt`: Dependências Python necessárias.

---

## Tópicos MQTT Utilizados

- Broker: `broker.hivemq.com` (Porta 1883)
- `smartgym/station/status`: Publica estado da estação (`Livre` ou `Ocupada`), nome do aluno e UID do RFID.
- `smartgym/station/telemetry`: Publica contagem de repetições e ângulo articular em tempo real durante a execução.
- `smartgym/station/performance`: Publica resumo de conclusão da série (repetições, duração, cadência média, detecção de fadiga e tempo recomendado de descanso).

---

## Como Executar

### 1. Instalar dependências
```bash
pip install -r requirements.txt
```

### 2. Iniciar o Dashboard Web
```bash
python dashboard/app.py
```
Acesse no navegador: `http://localhost:5000`

### 3. Iniciar o Rastreador Visual (YOLO)
```bash
python vision/exercise_tracker.py
```
- Pressione `l` na janela da câmera para alternar login/logout simulado ou aguarde a aproximação da tag no ESP32.
- Segure o celular preto na mão para que o sistema valide a execução do peso.

### 4. (Opcional) Testar via Simulador ESP32
```bash
python simulator/esp32_simulator.py
```
