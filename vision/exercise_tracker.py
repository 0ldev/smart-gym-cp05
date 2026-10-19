#!/usr/bin/env python3
"""
Smart Gym - Exercise Tracker (YOLO Pose + Black Mass Weight Tracking)
FIAP - Checkpoint 05 - O Caso da Smart Gym (Turma 3ESPZ)

Funcionalidades:
1. Rastreamento de pose via YOLOv8 (ombro, cotovelo, punho).
2. Detecção do 'peso' (celular preto) como massa escura na mão do usuário.
3. Cálculo do ângulo de fechamento da articulação do cotovelo para contagem de repetições.
4. Análise de cadência e perda de ritmo para alerta de fadiga muscular.
5. Integração MQTT bidirecional:
   - Subscriber de 'smartgym/station/status' (inicia/encerra sessão com RFID do ESP32).
   - Publisher em 'smartgym/station/performance' ao concluir a série.
"""

import cv2
import numpy as np
import time
import json
import math
import threading
import paho.mqtt.client as mqtt
from ultralytics import YOLO

# ================= CONFIGURAÇÕES MQTT =================
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TOPIC_STATUS = "smartgym/station/status"
TOPIC_PERFORMANCE = "smartgym/station/performance"
TOPIC_TELEMETRY = "smartgym/station/telemetry"
CLIENT_ID = "SmartGym_Vision_Station01"

# ================= ESTADO GLOBAL DO SISTEMA =================
class GymSession:
    def __init__(self):
        self.station_status = "Livre"
        self.student_name = "Nenhum (Aguardando RFID)"
        self.rfid_uid = ""
        self.reps = 0
        self.stage = "DOWN" # 'DOWN' ou 'UP'
        self.angle = 0.0
        self.weight_detected = False
        self.session_active = False
        self.session_start_time = None
        self.last_rep_time = None
        self.rep_durations = []
        self.fatigue_detected = False
        self.rest_suggestion = 0
        self.lock = threading.Lock()

session = GymSession()

# ================= FUNÇÕES MATEMÁTICAS E GEOMÉTRICAS =================
def calculate_angle(a, b, c):
    """
    Calcula o ângulo entre 3 pontos (a: ombro, b: cotovelo, c: punho).
    Retorna o ângulo em graus no intervalo [0, 180].
    """
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)

    radians = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
    angle = np.abs(radians * 180.0 / np.pi)
    if angle > 180.0:
        angle = 360.0 - angle
    return angle

def detect_black_mass_in_hand(frame, wrist_pt, roi_radius=45):
    """
    Analisa uma região circular ao redor do punho para identificar
    o celular preto (massa escura atuando como halter/peso).
    Retorna (detected: bool, centroid: tuple, mask_contour: list)
    """
    h, w, _ = frame.shape
    x, y = int(wrist_pt[0]), int(wrist_pt[1])

    x1 = max(0, x - roi_radius)
    y1 = max(0, y - roi_radius)
    x2 = min(w, x + roi_radius)
    y2 = min(h, y + roi_radius)

    if x2 - x1 < 10 or y2 - y1 < 10:
        return False, None, None

    roi = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # Máscara para objetos pretos/escuros:
    # Baixa saturação e baixo valor de brilho (preto do celular)
    lower_black = np.array([0, 0, 0])
    upper_black = np.array([180, 255, 65])
    mask = cv2.inRange(hsv, lower_black, upper_black)

    # Limpeza morfológica
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        # Limiar de área mínima para confirmar que há um celular na mão
        if area > 180:
            M = cv2.moments(largest)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"]) + x1
                cy = int(M["m01"] / M["m00"]) + y1
                # Ajusta contorno para coordenadas globais
                global_contour = largest + np.array([[[x1, y1]]])
                return True, (cx, cy), global_contour

    return False, None, None

# ================= CALLBACKS MQTT =================
def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Conectado com código {rc}")
    client.subscribe(TOPIC_STATUS)
    print(f"[MQTT] Inscrito no tópico: {TOPIC_STATUS}")

def on_message(client, userdata, msg):
    global session
    try:
        payload = json.loads(msg.payload.decode())
        status = payload.get("status", "Livre")
        student = payload.get("student", "")
        uid = payload.get("rfid_uid", "")

        with session.lock:
            old_status = session.station_status
            session.station_status = status
            session.student_name = student if student else "Nenhum"
            session.rfid_uid = uid

            # Transição para OCUPADA (Início do Treino via RFID)
            if status == "Ocupada" and old_status != "Ocupada":
                session.session_active = True
                session.reps = 0
                session.stage = "DOWN"
                session.session_start_time = time.time()
                session.last_rep_time = time.time()
                session.rep_durations.clear()
                session.fatigue_detected = False
                print(f"\n[SESSÃO INICIADA] Aluno: {session.student_name} (UID: {session.rfid_uid})")

            # Transição para LIVRE (Finalização do Treino via RFID)
            elif status == "Livre" and old_status == "Ocupada":
                if session.session_active:
                    finish_session(client)
                session.session_active = False
                print(f"\n[SESSÃO ENCERRADA] Estação Livre.")
    except Exception as e:
        print(f"[MQTT ERRO] Falha ao processar mensagem: {e}")

def finish_session(mqtt_client):
    """Publica performance do treino no tópico MQTT"""
    duration = round(time.time() - (session.session_start_time or time.time()), 1)
    avg_cadence = round(np.mean(session.rep_durations), 2) if session.rep_durations else 0.0
    
    # Sugestão de descanso baseada em fadiga
    rest_time = 90 if session.fatigue_detected or session.reps >= 12 else 60

    perf_data = {
        "station_id": "smart_station_01",
        "student": session.student_name,
        "rfid_uid": session.rfid_uid,
        "reps": session.reps,
        "duration_seconds": duration,
        "avg_cadence_seconds": avg_cadence,
        "fatigue_detected": session.fatigue_detected,
        "recommended_rest_seconds": rest_time,
        "timestamp": int(time.time())
    }

    payload_str = json.dumps(perf_data)
    mqtt_client.publish(TOPIC_PERFORMANCE, payload_str, retain=False)
    print(f"[MQTT PUB PERFORMANCE] -> {payload_str}")

# ================= LOOP PRINCIPAL DO EXERCISE TRACKER =================
def run_tracker():
    print("=== SMART GYM - SISTEMA DE VISÃO COMPUTACIONAL (YOLO) ===")
    print("Carregando modelo YOLOv8 Pose...")
    model = YOLO("yolov8n-pose.pt")

    # Inicializa cliente MQTT em thread separada
    mqtt_client = mqtt.Client(client_id=CLIENT_ID)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"Aviso: Não foi possível conectar ao broker MQTT ({e}). Operando offline.")

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("AVISO: Câmera não encontrada no índice 0. Tentando vídeo de teste sintético...")

    fps_time = time.time()
    
    while True:
        ret, frame = cap.read() if cap.isOpened() else (True, np.zeros((480, 640, 3), dtype=np.uint8))
        if not ret:
            break

        frame = cv2.flip(frame, 1) # Efeito espelho
        h, w, _ = frame.shape

        # Processa inferência YOLO Pose
        results = model(frame, verbose=False, conf=0.5)
        
        tracked_angle = None
        weight_detected = False
        weight_pos = None
        contour_draw = None

        if results and len(results) > 0 and results[0].keypoints is not None:
            keypoints = results[0].keypoints.xy.cpu().numpy()
            if len(keypoints) > 0:
                kpts = keypoints[0] # Primeiro usuário detectado
                conf = results[0].keypoints.conf[0].cpu().numpy() if results[0].keypoints.conf is not None else None

                # Pontos do braço direito: Ombro (6), Cotovelo (8), Punho (10)
                # Pontos do braço esquerdo: Ombro (5), Cotovelo (7), Punho (9)
                r_shoulder, r_elbow, r_wrist = kpts[6], kpts[8], kpts[10]
                l_shoulder, l_elbow, l_wrist = kpts[5], kpts[7], kpts[9]

                # Seleção automática pelo braço visível (essencial para filmagem de perfil/lado)
                if conf is not None:
                    r_conf = float(np.mean([conf[6], conf[8], conf[10]]))
                    l_conf = float(np.mean([conf[5], conf[7], conf[9]]))
                else:
                    r_conf = 1.0 if (np.all(r_wrist > 0) and np.all(r_elbow > 0) and np.all(r_shoulder > 0)) else 0.0
                    l_conf = 1.0 if (np.all(l_wrist > 0) and np.all(l_elbow > 0) and np.all(l_shoulder > 0)) else 0.0

                if r_conf > 0.35 or l_conf > 0.35:
                    if r_conf >= l_conf:
                        shoulder, elbow, wrist = r_shoulder, r_elbow, r_wrist
                        side = "Direito"
                    else:
                        shoulder, elbow, wrist = l_shoulder, l_elbow, l_wrist
                        side = "Esquerdo"

                    # Cálculo do ângulo do cotovelo
                    tracked_angle = calculate_angle(shoulder, elbow, wrist)
                    session.angle = tracked_angle

                    # Rastreamento da massa escura (celular / peso) na mão
                    weight_detected, weight_pos, contour_draw = detect_black_mass_in_hand(frame, wrist)
                    session.weight_detected = weight_detected

                    # Desenho do esqueleto do braço
                    cv2.line(frame, tuple(shoulder.astype(int)), tuple(elbow.astype(int)), (255, 255, 0), 4)
                    cv2.line(frame, tuple(elbow.astype(int)), tuple(wrist.astype(int)), (255, 255, 0), 4)
                    for pt in [shoulder, elbow, wrist]:
                        cv2.circle(frame, tuple(pt.astype(int)), 7, (0, 165, 255), -1)

                    # Destaca detecção do peso/celular
                    if weight_detected and weight_pos:
                        cv2.drawContours(frame, [contour_draw], -1, (0, 255, 0), 2)
                        cv2.circle(frame, weight_pos, 8, (0, 255, 0), -1)
                        cv2.putText(frame, "PESO (CELULAR) OK", (weight_pos[0] - 50, weight_pos[1] - 20),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    else:
                        cv2.circle(frame, tuple(wrist.astype(int)), 35, (0, 0, 255), 2)
                        cv2.putText(frame, "SEGURE O PESO!", (int(wrist[0]) - 50, int(wrist[1]) - 20),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

                    # Exibe o valor do ângulo no cotovelo
                    cv2.putText(frame, f"{int(tracked_angle)}º", (int(elbow[0]) + 15, int(elbow[1])),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

                    # ================= LÓGICA DE CONTAGEM E ÂNGULO =================
                    # O exercício só computa se o usuário estiver autenticado (ou em modo simulação)
                    # Ângulo de abertura (extensão): > 145 graus
                    # Ângulo de fechamento (flexão/pico da contração): < 50 graus
                    if session.session_active or session.station_status == "Ocupada":
                        if tracked_angle > 145:
                            session.stage = "DOWN"

                        if tracked_angle < 50 and session.stage == "DOWN":
                            if weight_detected: # Valida que está com o peso na mão
                                session.stage = "UP"
                                session.reps += 1
                                now = time.time()
                                if session.last_rep_time:
                                    rep_duration = now - session.last_rep_time
                                    session.rep_durations.append(rep_duration)
                                    
                                    # Análise de fadiga (perda acentuada de ritmo ou excesso de lentidão)
                                    avg_time = np.mean(session.rep_durations[:-1]) if len(session.rep_durations) > 1 else rep_duration
                                    if rep_duration > avg_time * 1.75 and rep_duration > 3.5:
                                        session.fatigue_detected = True
                                session.last_rep_time = now

                                # Publica telemetria em tempo real a cada repetição
                                telem = {
                                    "reps": session.reps,
                                    "angle": round(tracked_angle, 1),
                                    "student": session.student_name,
                                    "fatigue": session.fatigue_detected
                                }
                                mqtt_client.publish(TOPIC_TELEMETRY, json.dumps(telem))

        # ================= INTERFACE VISUAL (OVERLAY HEADS-UP) =================
        # Barra superior com status da estação
        status_color = (0, 0, 255) if session.station_status == "Ocupada" else (0, 200, 0)
        cv2.rectangle(frame, (0, 0), (w, 80), (25, 25, 25), -1)
        cv2.rectangle(frame, (0, 77), (w, 80), status_color, -1)

        cv2.putText(frame, f"STATUS: {session.station_status.upper()}", (20, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, status_color, 2)
        cv2.putText(frame, f"ALUNO: {session.student_name}", (20, 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 2)

        # Contador de repetições grande no canto superior direito
        cv2.rectangle(frame, (w - 180, 10), (w - 20, 70), (45, 45, 45), -1)
        cv2.putText(frame, f"REPS: {session.reps}", (w - 165, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)

        # Indicador de fadiga
        if session.fatigue_detected:
            cv2.rectangle(frame, (20, h - 70), (400, h - 20), (0, 0, 180), -1)
            cv2.putText(frame, "FADIGA DETECTADA! DESCANSO: 90s", (30, h - 38),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        # Exibe taxa de quadros (FPS)
        curr_time = time.time()
        fps = 1 / (curr_time - fps_time + 1e-6)
        fps_time = curr_time
        cv2.putText(frame, f"FPS: {int(fps)}", (w - 100, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

        # Controles rápidos pelo teclado:
        # 'l' = Simular RFID Login / Logout
        # 'r' = Resetar contagem
        # 'q' = Sair
        cv2.imshow("Smart Gym - Monitoramento de Treino (YOLO + RFID)", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('l'):
            # Alterna login simulado
            new_st = "Livre" if session.station_status == "Ocupada" else "Ocupada"
            sim_payload = json.dumps({
                "station_id": "smart_station_01",
                "status": new_st,
                "student": "Aluno Teste Local" if new_st == "Ocupada" else "",
                "rfid_uid": "SIM12345"
            })
            mqtt_client.publish(TOPIC_STATUS, sim_payload)
        elif key == ord('r'):
            session.reps = 0
            session.rep_durations.clear()
            session.fatigue_detected = False

    if cap.isOpened():
        cap.release()
    cv2.destroyAllWindows()
    mqtt_client.loop_stop()

if __name__ == "__main__":
    run_tracker()
