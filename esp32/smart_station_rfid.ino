/*
 * =====================================================================
 * FIAP - Engenharia de Software | Physical Computing (IoT & IoB)
 * Checkpoint 05 - O Caso da Smart Gym: A Evolução do Treino Digital
 * Turma: 3ESPZ
 * 
 * Descrição:
 * Firmware ESP32 para autenticação via leitor RFID RC522 e telemetria MQTT.
 * Publica status de ocupação da estação ("Livre" / "Ocupada") e dados do
 * aluno autenticado.
 * =====================================================================
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <SPI.h>
#include <MFRC522.h>

// ================= CONFIGURAÇÕES DE REDE & MQTT =================
const char* WIFI_SSID     = "SEU_WIFI_SSID";
const char* WIFI_PASSWORD = "SUA_SENHA_WIFI";

// Broker público HiveMQ (pode ser substituído por Mosquitto ou broker local)
const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* MQTT_CLIENT_ID = "SmartGym_ESP32_Station01";

// Tópicos MQTT
const char* TOPIC_STATUS      = "smartgym/station/status";
const char* TOPIC_PERFORMANCE = "smartgym/station/performance";

// ================= PINAGEM DO HARDWARE =================
// MFRC522 via SPI (ESP32 Padrão)
#define SS_PIN    5    // SDA / SS do RC522
#define RST_PIN   22   // RST do RC522
// SCK  -> GPIO 18
// MOSI -> GPIO 23
// MISO -> GPIO 19

// Atuadores / Sinalizadores
#define LED_LIVRE    2   // LED Verde (Estação Livre)
#define LED_OCUPADA  4   // LED Vermelho (Estação Ocupada)
#define BUZZER_PIN   15  // Feedback sonoro de bipe

// Instâncias dos periféricos
MFRC522 rfid(SS_PIN, RST_PIN);
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// ================= BANCO DE ALUNOS (RFID UIDs) =================
struct Student {
  String uid;
  String name;
};

// Cadastre as tags dos participantes aqui
Student registeredStudents[] = {
  {"A1B2C3D4", "Carlos Silva"},
  {"E5F6G7H8", "Mariana Costa"},
  {"12345678", "Lucas Augusto"}
};
const int TOTAL_STUDENTS = sizeof(registeredStudents) / sizeof(registeredStudents[0]);

// ================= MÁQUINA DE ESTADOS =================
enum StationState {
  STATE_LIVRE,
  STATE_OCUPADA
};

StationState currentState = STATE_LIVRE;
String currentStudentName = "";
String currentStudentUID = "";
unsigned long sessionStartTime = 0;

// ================= PROTÓTIPOS =================
void setupWiFi();
void reconnectMQTT();
void beep(int frequency, int durationMs);
void publishStatus(const char* status, const String& student, const String& uid);
String getUIDString(MFRC522::Uid *uid);
String findStudentName(const String& uidStr);

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== INICIANDO SMART GYM STATION (ESP32 + RFID) ===");

  pinMode(LED_LIVRE, OUTPUT);
  pinMode(LED_OCUPADA, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  // Estado inicial:
  digitalWrite(LED_LIVRE, HIGH);
  digitalWrite(LED_OCUPADA, LOW);

  // Inicializa SPI e RC522
  SPI.begin();
  rfid.PCD_Init();
  delay(100);
  rfid.PCD_DumpVersionToSerial();

  // Conexões de Rede
  setupWiFi();
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  beep(1000, 150);
  Serial.println("Estação pronta. Aproxime a tag RFID.");
}

void loop() {
  if (!mqttClient.connected()) {
    reconnectMQTT();
  }
  mqttClient.loop();

  // Verifica presença de nova tag RFID
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    return;
  }

  String scannedUID = getUIDString(&(rfid.uid));
  Serial.print("\n[RFID] Tag detectada. UID: ");
  Serial.println(scannedUID);

  String studentName = findStudentName(scannedUID);
  if (studentName == "") {
    studentName = "Aluno Desconhecido (" + scannedUID + ")";
  }

  // Alternância de Estado (Toggle Login / Logout)
  if (currentState == STATE_LIVRE) {
    // LOGIN
    currentState = STATE_OCUPADA;
    currentStudentName = studentName;
    currentStudentUID = scannedUID;
    sessionStartTime = millis();

    digitalWrite(LED_LIVRE, LOW);
    digitalWrite(LED_OCUPADA, HIGH);

    // Bipe duplo de confirmação
    beep(1800, 100);
    delay(50);
    beep(2400, 150);

    Serial.println("[ESTADO] Estação OCUPADA por: " + currentStudentName);
    publishStatus("Ocupada", currentStudentName, currentStudentUID);
  } else {
    // LOGOUT (apenas o mesmo usuário ou tag mestre pode deslogar)
    currentState = STATE_LIVRE;
    Serial.println("[ESTADO] Treino finalizado por: " + currentStudentName);

    digitalWrite(LED_LIVRE, HIGH);
    digitalWrite(LED_OCUPADA, LOW);

    // Bipe descendente de logout
    beep(2000, 120);
    delay(50);
    beep(1000, 200);

    publishStatus("Livre", "", "");
    currentStudentName = "";
    currentStudentUID = "";
  }

  // Pausa para evitar múltiplas leituras consecutivas da mesma tag
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  delay(1500);
}

void setupWiFi() {
  Serial.print("Conectando ao WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Conectado! IP: " + WiFi.localIP().toString());
  } else {
    Serial.println("\n[WiFi] Falha ao conectar. Operando em modo offline.");
  }
}

void reconnectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("[MQTT] Conectando ao Broker... ");
    if (mqttClient.connect(MQTT_CLIENT_ID)) {
      Serial.println("Conectado com sucesso!");
      // Publica status inicial
      publishStatus(currentState == STATE_LIVRE ? "Livre" : "Ocupada", currentStudentName, currentStudentUID);
    } else {
      Serial.print("Falhou, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" Tentando novamente em 3 segundos...");
      delay(3000);
      break; // Não trava o loop se estiver sem internet
    }
  }
}

void publishStatus(const char* status, const String& student, const String& uid) {
  if (!mqttClient.connected()) return;

  // Payload JSON conforme especificação do Checkpoint 05
  String payload = "{";
  payload += "\"station_id\":\"smart_station_01\",";
  payload += "\"status\":\"" + String(status) + "\",";
  payload += "\"student\":\"" + student + "\",";
  payload += "\"rfid_uid\":\"" + uid + "\",";
  payload += "\"timestamp\":" + String(millis()) + "";
  payload += "}";

  mqttClient.publish(TOPIC_STATUS, payload.c_str(), true); // retain=true
  Serial.println("[MQTT PUB] Topic: " + String(TOPIC_STATUS) + " -> " + payload);
}

String getUIDString(MFRC522::Uid *uid) {
  String uidStr = "";
  for (byte i = 0; i < uid->size; i++) {
    if (uid->uidByte[i] < 0x10) uidStr += "0";
    uidStr += String(uid->uidByte[i], HEX);
  }
  uidStr.toUpperCase();
  return uidStr;
}

String findStudentName(const String& uidStr) {
  for (int i = 0; i < TOTAL_STUDENTS; i++) {
    if (registeredStudents[i].uid.equalsIgnoreCase(uidStr)) {
      return registeredStudents[i].name;
    }
  }
  return "";
}

void beep(int frequency, int durationMs) {
  tone(BUZZER_PIN, frequency, durationMs);
}
