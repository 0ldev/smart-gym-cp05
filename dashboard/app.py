#!/usr/bin/env python3
"""
Smart Gym - Web Dashboard (Flask + MQTT + Server-Sent Events)
FIAP - Checkpoint 05 - O Caso da Smart Gym (Turma 3ESPZ)

Exibe status em tempo real das estações (Livre/Ocupada) e histórico recente
de treinos e repetições atualizado via MQTT sem necessidade de refresh.
"""

import json
import time
from datetime import datetime
from queue import Queue
from flask import Flask, render_template, Response, jsonify
import paho.mqtt.client as mqtt

app = Flask(__name__)

# ================= CONFIGURAÇÕES MQTT =================
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TOPIC_STATUS = "smartgym/station/status"
TOPIC_PERFORMANCE = "smartgym/station/performance"
TOPIC_TELEMETRY = "smartgym/station/telemetry"
CLIENT_ID = "SmartGym_WebDashboard_Subscriber"

# Fila para Server-Sent Events (SSE)
event_listeners = []

# Estado global da estação e histórico
state = {
    "station_id": "smart_station_01",
    "status": "Livre",
    "student": "Nenhum",
    "rfid_uid": "",
    "reps": 0,
    "angle": 0,
    "fatigue": False,
    "last_update": time.strftime("%H:%M:%S")
}

history_log = [
    {
        "id": 1,
        "student": "Mariana Costa",
        "reps": 15,
        "duration": "42s",
        "cadence": "2.8s/rep",
        "fatigue": "Não",
        "rest": "60s",
        "timestamp": "14:15:30"
    }
]

def broadcast_event(event_type, data):
    """Envia dados para todos os navegadores conectados via SSE"""
    message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    for q in list(event_listeners):
        try:
            q.put_nowait(message)
        except Exception:
            event_listeners.remove(q)

# ================= MQTT HANDLERS =================
def on_connect(client, userdata, flags, rc):
    print(f"[MQTT DASHBOARD] Conectado ao broker! RC={rc}")
    client.subscribe([(TOPIC_STATUS, 0), (TOPIC_PERFORMANCE, 0), (TOPIC_TELEMETRY, 0)])
    print(f"[MQTT DASHBOARD] Inscrito em {TOPIC_STATUS}, {TOPIC_PERFORMANCE}, {TOPIC_TELEMETRY}")

def on_message(client, userdata, msg):
    global state, history_log
    try:
        payload = json.loads(msg.payload.decode())
        topic = msg.topic

        if topic == TOPIC_STATUS:
            state["status"] = payload.get("status", "Livre")
            state["student"] = payload.get("student", "Nenhum")
            state["rfid_uid"] = payload.get("rfid_uid", "")
            if state["status"] == "Ocupada":
                state["reps"] = 0
                state["fatigue"] = False
            state["last_update"] = datetime.now().strftime("%H:%M:%S")
            broadcast_event("status_update", state)
            print(f"[MQTT EVT] Status alterado: {state['status']} ({state['student']})")

        elif topic == TOPIC_TELEMETRY:
            state["reps"] = payload.get("reps", state["reps"])
            state["angle"] = payload.get("angle", state["angle"])
            state["fatigue"] = payload.get("fatigue", state["fatigue"])
            broadcast_event("telemetry_update", {
                "reps": state["reps"],
                "angle": state["angle"],
                "fatigue": state["fatigue"]
            })

        elif topic == TOPIC_PERFORMANCE:
            new_entry = {
                "id": len(history_log) + 1,
                "student": payload.get("student", "Desconhecido"),
                "reps": payload.get("reps", 0),
                "duration": f"{payload.get('duration_seconds', 0)}s",
                "cadence": f"{payload.get('avg_cadence_seconds', 0)}s/rep",
                "fatigue": "SIM (Alerta)" if payload.get("fatigue_detected") else "Não",
                "rest": f"{payload.get('recommended_rest_seconds', 60)}s",
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            history_log.insert(0, new_entry) # Insere no topo
            broadcast_event("history_update", new_entry)
            print(f"[MQTT EVT] Novo treino registrado no histórico: {new_entry}")

    except Exception as e:
        print(f"[MQTT ERRO] Processamento de msg falhou: {e}")

# Inicia o cliente MQTT
mqtt_client = mqtt.Client(client_id=CLIENT_ID)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()

# ================= ROTAS FLASK =================
@app.route("/")
def index():
    return render_template("index.html", state=state, history=history_log)

@app.route("/api/state")
def get_state():
    return jsonify({"state": state, "history": history_log})

@app.route("/events")
def events():
    def stream():
        q = Queue()
        event_listeners.append(q)
        try:
            # Envia estado inicial no primeiro contato
            yield f"event: init\ndata: {json.dumps({'state': state, 'history': history_log})}\n\n"
            while True:
                msg = q.get()
                yield msg
        except GeneratorExit:
            event_listeners.remove(q)

    return Response(stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"
    })

if __name__ == "__main__":
    print("=== INICIANDO SMART GYM DASHBOARD (Porta 5000) ===")
    app.run(host="0.0.0.0", port=5000, debug=False)
