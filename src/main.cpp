#include <RadioLib.h>
#include <SPI.h>
#include <ArduinoQueue.h>
#include <ArduinoJson.h>

// Add forward declaration
void initializeRadio();

#define CC1101_SPI_MISO 19
#define CC1101_SPI_CS    5
#define CC1101_GDO0     27
#define CC1101_GDO2     22

Module module(CC1101_SPI_CS, CC1101_GDO0, RADIOLIB_NC, CC1101_GDO2);
CC1101 radio = CC1101(&module);

ArduinoQueue<String> packetQueue(50);
bool transmitMode = true;
float currentFreq = 868.0;

struct PacketHeader {
  char type[8];
  uint16_t seq;
  uint16_t total;
  char filename[32];
  char checksum[3];
  size_t data_len;
};

void setup() {
  Serial.begin(115200);
  SPI.begin();
  initializeRadio();
}

void initializeRadio() {
  int state = radio.begin(currentFreq);
  if(state != RADIOLIB_ERR_NONE) {
    Serial.print("<ERROR|RADIO_INIT_CODE:");
    Serial.print(state);
    Serial.println(">");
    while(true);
  }
  radio.setBitRate(1.2);
  radio.setRxBandwidth(58.0);
  radio.setFrequencyDeviation(5.0);
  radio.setOutputPower(10);
}

uint8_t calculateChecksum(String payload) {
  uint8_t sum = 0;
  for(char c : payload) sum = (sum + c) % 256;
  return sum;
}

void handleRadioCommand(String command) {
  if(command.startsWith("<SET|")) {
    currentFreq = command.substring(5, command.indexOf(',')).toFloat();
    radio.setFrequency(currentFreq);
    Serial.println("<STATUS|FREQ_SET>");
  }
  else if(command.startsWith("<TXMODE>")) {
    transmitMode = true;
    Serial.println("<STATUS|TX_MODE>");
  }
  else if(command.startsWith("<RXMODE>")) {
    transmitMode = false;
    Serial.println("<STATUS|RX_MODE>");
  }
  else if(command.startsWith("<RX_READY>")) {
    Serial.println("<STATUS|RX_READY>");
  }
  else if(command.startsWith("<FILE|")) {
    String filename = command.substring(6, command.indexOf('|', 6));
    int total = command.substring(command.indexOf('|', 6)+1, command.lastIndexOf('|')).toInt();
    int size = command.substring(command.lastIndexOf('|')+1, command.indexOf('>')).toInt();
    
    Serial.print("<STATUS|FILE_START|");
    Serial.print(filename);
    Serial.print("|");
    Serial.print(total);
    Serial.println(">");
  }
  else if(command.startsWith("<DATA|")) {
    packetQueue.enqueue(command.substring(6, command.indexOf('>')));
  }
}

void handleTransmission() {
  if(!packetQueue.isEmpty()) {
    String packet = packetQueue.dequeue();
    int state = radio.transmit(packet);
    
    if(state == RADIOLIB_ERR_NONE) {
      Serial.println("<STATUS|TX_SUCCESS>");
    } else {
      Serial.println("<STATUS|TX_FAIL>");
      packetQueue.enqueue(packet);
    }
  }
}

void handleReception() {
  String received;
  int16_t state = radio.receive(received);

  if(state == RADIOLIB_ERR_NONE) {
    DynamicJsonDocument doc(256);
    DeserializationError error = deserializeJson(doc, received);
    
    if(error) {
      Serial.print("<ERROR|JSON:");
      Serial.print(error.c_str());
      Serial.println(">");
      return;
    }

    PacketHeader header;
    strlcpy(header.type, doc["type"], sizeof(header.type));
    header.seq = doc["seq"];
    header.total = doc["total"];
    strlcpy(header.filename, doc["filename"], sizeof(header.filename));
    strlcpy(header.checksum, doc["checksum"], sizeof(header.checksum));
    header.data_len = doc["data_len"];

    String data = doc["data"].as<String>();
    uint8_t calcSum = calculateChecksum(data);
    
    if(String(calcSum, HEX) != String(header.checksum)) {
      Serial.println("<STATUS|CHECKSUM_ERR>");
      return;
    }

    Serial.print("<DATA|");
    serializeJson(doc, Serial);
    Serial.println(">");
  }
}

void loop() {
  if(Serial.available()) {
    String command = Serial.readStringUntil('\n');
    handleRadioCommand(command);
  }
  
  if(transmitMode) {
    handleTransmission();
  } else {
    handleReception();
  }
}
