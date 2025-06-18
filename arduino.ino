/*
 * RFID Projektmanager - Arduino Firmware
 * ======================================
 * 
 * Diese Firmware implementiert ein RFID-basiertes Projektzeit-Tracking-System
 * mit LCD-Anzeige und serieller Kommunikation zu einer PC-Anwendung.
 * 
 * Hardware-Anforderungen:
 * - Arduino Uno R3
 * - RC522 RFID-Reader (SPI)
 * - 16x2 LCD Display (parallel)
 * - RFID-Tags für Projekte
 * - Admin-RFID-Karte für Löschfunktion
 * 
 * Funktionen:
 * - Erkennung von RFID-Karten
 * - Start/Pause von Projekten durch Kartenberührung
 * - Zeiterfassung mit Millisekunden-Genauigkeit
 * - Admin-Modus zum Löschen von Projekten
 * - LCD-Anzeige mit Live-Zeitanzeige
 * - Serielle Kommunikation für PC-Integration
 * 
 * Pin-Belegung:6
 * - RFID: SS=10, RST=9, SPI-Bus (MOSI=11, MISO=12, SCK=13)
 * - LCD: RS=7, Enable=6, D4=5, D5=4, D6=3, D7=2
 * 
 * Autor: Mika Solinsky, Florian Kröger
 * Version: 1.0
 * Datum: 18.06.2025
 */

#include <SPI.h>
#include <MFRC522.h>
#include <LiquidCrystal.h>

// === Hardware-Konfiguration ===
#define SS_PIN 10        // RFID Slave Select Pin
#define RST_PIN 9        // RFID Reset Pin
MFRC522 mfrc522(SS_PIN, RST_PIN);

// LCD-Pins: RS, Enable, D4, D5, D6, D7
LiquidCrystal lcd(7, 6, 5, 4, 3, 2);

// === Projekt-Verwaltung ===
const int MAX_PROJECTS = 10;                    // Maximale Anzahl Projekte
String knownUIDs[MAX_PROJECTS];                 // RFID-UIDs der Projekte
String projectNames[MAX_PROJECTS];              // Projektnamen
bool projectActive[MAX_PROJECTS];               // Status: aktiv/pausiert
unsigned long projectStartTime[MAX_PROJECTS];   // Startzeit der aktuellen Session
unsigned long projectAccumulatedTime[MAX_PROJECTS]; // Akkumulierte Gesamtzeit
int projectCount = 0;                           // Anzahl registrierter Projekte

// === Admin-Funktionen ===
const String ADMIN_UID = "74:8a:71:16";        // UID der Admin-Karte
bool pendingDeletion = false;                   // Flag für Lösch-Modus

// === Status-Variablen ===
bool waitingForProjectName = false;             // Warten auf Projektname vom PC
String newUID = "";                             // UID der neuen Karte
unsigned long displayFreezeUntil = 0;          // LCD-Freeze für Nachrichten

/**
 * Löscht eine Zeile des LCD-Displays.
 * 
 * @param line Zeilennummer (0 oder 1)
 */
void clearLCDLine(int line) {
  lcd.setCursor(0, line);
  lcd.print("                "); // 16 Leerzeichen für 16x2 Display
}

/**
 * Arduino Setup-Funktion.
 * 
 * Initialisiert:
 * - Serielle Kommunikation (9600 Baud)
 * - SPI-Bus für RFID-Reader
 * - RFID-Reader
 * - LCD-Display
 */
void setup() {
  Serial.begin(9600);
  SPI.begin();
  mfrc522.PCD_Init();
  lcd.begin(16, 2);
  lcd.print("Projekt?");
}

/**
 * Arduino Hauptschleife.
 * 
 * Verarbeitet:
 * 1. Eingehende serielle Daten (Projektnamen vom PC)
 * 2. RFID-Karten-Events
 * 3. LCD-Updates für laufende Projekte
 */
void loop() {
  // === Serielle Eingabe verarbeiten ===
  if (waitingForProjectName && Serial.available()) {
    String name = Serial.readStringUntil('\n');
    name.trim();

    if (projectCount < MAX_PROJECTS) {
      // Neues Projekt registrieren
      knownUIDs[projectCount] = newUID;
      projectNames[projectCount] = name;
      projectActive[projectCount] = false;
      projectStartTime[projectCount] = 0;
      projectAccumulatedTime[projectCount] = 0;

      Serial.println("Projekt hinzugefügt: " + name + " (" + newUID + ")");
      
      // LCD-Bestätigung anzeigen
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Projekt hinzugefuegt:");
      lcd.setCursor(0, 1);
      lcd.print(name);
      delay(3000);
      lcd.clear();
      lcd.print("Projekt?");
      projectCount++;
    } else {
      // Maximale Projektanzahl erreicht
      Serial.println("Max. Anzahl erreicht!");
      lcd.clear();
      lcd.print("Max erreicht!");
      delay(2000);
      lcd.clear();
      lcd.print("Projekt?");
    }

    waitingForProjectName = false;
    return;
  }

  // === RFID-Karten verarbeiten ===
  if (mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
    // UID als String formatieren (HEX mit Doppelpunkten)
    String uidString = "";
    for (byte i = 0; i < mfrc522.uid.size; i++) {
      if (mfrc522.uid.uidByte[i] < 0x10) uidString += "0";
      uidString += String(mfrc522.uid.uidByte[i], HEX);
      if (i < mfrc522.uid.size - 1) uidString += ":";
    }

    Serial.println("RFID erkannt: " + uidString);

    // === Admin-Karte verarbeiten ===
    if (uidString == ADMIN_UID) {
      pendingDeletion = !pendingDeletion; // Lösch-Modus umschalten
      lcd.clear();
      if (pendingDeletion) {
        lcd.print("Loeschmodus an");
        lcd.setCursor(0, 1);
        lcd.print("Projekt scannen");
      } else {
        lcd.print("Abbruch");
        lcd.setCursor(0, 1);
        lcd.print("Zurueck...");
      }
      delay(3000);
      lcd.clear();
      lcd.print("Projekt?");
      mfrc522.PICC_HaltA();
      delay(1000);
      return;
    }

    // === Projekt löschen (wenn Lösch-Modus aktiv) ===
    if (pendingDeletion) {
      for (int i = 0; i < projectCount; i++) {
        if (knownUIDs[i] == uidString) {
          // Gesamtzeit berechnen (inklusive aktueller Session)
          unsigned long total = projectAccumulatedTime[i];
          if (projectActive[i]) {
            total += millis() - projectStartTime[i];
            projectActive[i] = false;
          }

          // Zeit formatieren für Ausgabe
          int sek = (total / 1000) % 60;
          int min = (total / 60000) % 60;
          int std = (total / 3600000);

          // LCD-Bestätigung
          lcd.clear();
          lcd.setCursor(0, 0);
          lcd.print(projectNames[i]);
          lcd.setCursor(0, 1);
          lcd.print("geloescht");

          // Serielle Ausgabe mit Zeitangabe
          Serial.println("Projekt geloescht: " + projectNames[i] + " (" + String(std) + "h " + String(min) + "m " + String(sek) + "s)");

          // Projekt aus Arrays entfernen (Array kompaktieren)
          for (int j = i; j < projectCount - 1; j++) {
            knownUIDs[j] = knownUIDs[j + 1];
            projectNames[j] = projectNames[j + 1];
            projectActive[j] = projectActive[j + 1];
            projectStartTime[j] = projectStartTime[j + 1];
            projectAccumulatedTime[j] = projectAccumulatedTime[j + 1];
          }
          projectCount--;
          pendingDeletion = false;
          delay(3000);
          lcd.clear();
          lcd.print("Projekt?");
          mfrc522.PICC_HaltA();
          delay(1000);
          return;
        }
      }
      lcd.clear();
      lcd.print("Nicht gefunden");
      delay(2000);
      lcd.clear();
      lcd.print("Projekt?");
      pendingDeletion = false;
      mfrc522.PICC_HaltA();
      delay(1000);
      return;
    }

    bool found = false;
    int index = -1;
    for (int i = 0; i < projectCount; i++) {
      if (knownUIDs[i] == uidString) {
        found = true;
        index = i;
        break;
      }
    }

    if (found) {
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print(projectNames[index]);

      if (!projectActive[index]) {
        // Stoppe alle laufenden Projekte
        for (int i = 0; i < projectCount; i++) {
          if (projectActive[i]) {
            projectAccumulatedTime[i] += millis() - projectStartTime[i];
            projectActive[i] = false;
          }
        }
        // Starte aktuelles Projekt
        projectActive[index] = true;
        projectStartTime[index] = millis();
        lcd.setCursor(0, 1);
        lcd.print("Gestartet");
        Serial.println("Projekt gestartet: " + projectNames[index]);
      } else {
        // Pausiere Projekt
        projectAccumulatedTime[index] += millis() - projectStartTime[index];
        projectActive[index] = false;
        lcd.setCursor(0, 1);
        lcd.print("Pausiert");
        Serial.println("Projekt pausiert: " + projectNames[index]);
      }

      displayFreezeUntil = millis() + 3000;
    } else {
      Serial.println("Unbekannte UID: " + uidString);
      Serial.println("Bitte Projektnamen eingeben und bestätigen:");
      newUID = uidString;
      waitingForProjectName = true;
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Unbekanntes Tag");
      lcd.setCursor(0, 1);
      lcd.print("-> Name am PC");
    }

    mfrc522.PICC_HaltA();
    delay(1000);
  }

  if (millis() > displayFreezeUntil) {
    bool anyActive = false;
    for (int i = 0; i < projectCount; i++) {
      if (projectActive[i]) {
        anyActive = true;
        unsigned long laufzeit = projectAccumulatedTime[i] + (millis() - projectStartTime[i]);
        int sek = (laufzeit / 1000) % 60;
        int min = (laufzeit / 60000) % 60;
        int std = (laufzeit / 3600000);

        lcd.setCursor(0, 0);
        clearLCDLine(0);
        lcd.setCursor(0, 0);
        lcd.print(projectNames[i]);

        lcd.setCursor(0, 1);
        clearLCDLine(1);
        lcd.setCursor(0, 1);
        if (std < 10) lcd.print("0");
        lcd.print(std); lcd.print("h ");
        if (min < 10) lcd.print("0");
        lcd.print(min); lcd.print("m ");
        if (sek < 10) lcd.print("0");
        lcd.print(sek); lcd.print("s");
        break;
      }
    }
    if (!anyActive && !waitingForProjectName && !pendingDeletion) {
      lcd.setCursor(0, 0);
      clearLCDLine(0);
      lcd.setCursor(0, 0);
      lcd.print("Projekt?");
    }
  }
}
