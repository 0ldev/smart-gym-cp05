#!/usr/bin/env python3
"""
Smart Gym - ESP32 & RFID Simulator
FIAP - Checkpoint 05 (Turma 3ESPZ)

Permite simular o envio de eventos MQTT como se fossem gerados
pelo ESP32 com o leitor RFID MFRC522.
"""

import json
import time
import paho.mqtt.client as mqtt

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TOPIC_STATUS = "smartgym/station/status"

STUDENTS = {
    "1": {"name": "Carlos Silva", "uid": "A1B2C3D4"},
    "2": {"name": "Mariana Costa", "uid": "E5F6G7H8"},
    "3": {"name": "Lucas Augusto", "uid": "12345678"}
}

def publish_state(client, status, student="", uid=""):
    payload = {
        "station_id": "smart_station_01",
        "status": status,
        "student": student,
        "rfid_uid": uid,
        "timestamp": int(time.time() * 1000)
    }
    data_str = json.dumps(payload)
    client.publish(TOPIC_STATUS, data_str, retain=True)
    print(f"\n[SIMULADOR ESP32] Publicado no tópico '{TOPIC_STATUS}':")
    print(f"  -> {data_str}\n")

def main():
    print("=== SIMULADOR DE ESP32 + RFID MFRC522 ===")
    print(f"Conectando ao broker MQTT ({MQTT_BROKER}:{MQTT_PORT})...")
    
    client = mqtt.Client(client_id="ESP32_RFID_Simulator")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    time.sleep(1)
    print("Conectado com sucesso!\n")

    current_state = "Livre"
    current_user = ""

    while True:
        print("-" * 45)
        print(f"Estado atual da estação: [{current_state}] Aluno: [{current_user or 'Nenhum'}]")
        print("Escolha uma ação RFID:")
        print("1. Bipar tag de Carlos Silva (Login/Logout)")
        print("2. Bipar tag de Mariana Costa (Login/Logout)")
        print("3. Bipar tag de Lucas Augusto (Login/Logout)")
        print("4. Forçar estação para LIVRE (Logout Geral)")
        print("0. Sair do simulador")
        print("-" * 45)

        choice = input("Digite a opção: ").strip()
        if choice == "0":
            break
        elif choice in ["1", "2", "3"]:
            student_info = STUDENTS[choice]
            if current_state == "Livre":
                # Login
                current_state = "Ocupada"
                current_user = student_info["name"]
                publish_state(client, "Ocupada", student_info["name"], student_info["uid"])
            else:
                # Logout
                current_state = "Livre"
                current_user = ""
                publish_state(client, "Livre", "", "")
        elif choice == "4":
            current_state = "Livre"
            current_user = ""
            publish_state(client, "Livre", "", "")
        else:
            print("Opção inválida!")

    client.loop_stop()
    client.disconnect()
    print("Simulador finalizado.")

if __name__ == "__main__":
    main()
