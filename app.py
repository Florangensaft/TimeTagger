"""
RFID Projektmanager - Python GUI Anwendung
==========================================

Diese Anwendung stellt eine grafische Benutzeroberfläche für das RFID-basierte 
Projektzeit-Tracking-System bereit. Sie kommuniziert über serielle Schnittstelle 
mit einem Arduino-basierten RFID-Reader.

Hauptfunktionen:
- Empfang und Anzeige von RFID-Events vom Arduino
- Verwaltung von Projekten und deren Arbeitszeiten
- Live-Anzeige der aktuellen und akkumulierten Projektzeiten
- Hinzufügen neuer Projekte über GUI-Eingabe

Architektur:
- Tkinter-basierte GUI mit zwei Hauptbereichen (Konsole + Projektliste)
- Separater Thread für serielle Kommunikation
- Timer-basierte Live-Updates der Zeitanzeigen
- Thread-sichere GUI-Updates über root.after()

Autor: Mika Solinsky, Florian Kröger
Version: 1.0
Datum: 18.06.2025
"""

import tkinter as tk
from tkinter import scrolledtext, ttk
import serial
import threading
import time
from datetime import datetime

# === Konfiguration ===
COM_PORT = 'COM7'        # Serielle Schnittstelle zum Arduino
BAUD_RATE = 9600         # Übertragungsgeschwindigkeit

# === Globale Variablen ===
ser = None               # Serielle Verbindung
running = True           # Flag für Thread-Kontrolle
projects = {}            # Projekt-Dictionary: {name: {'start_time': timestamp, 'total_time': seconds, 'is_running': bool}}

# === GUI-Setup ===
root = tk.Tk()
root.title("RFID Projektmanager")
root.geometry("900x600")

# Hauptframe für Layout
main_frame = tk.Frame(root)
main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

# Grid-Konfiguration für responsives Layout
root.grid_rowconfigure(0, weight=1)
root.grid_columnconfigure(0, weight=1)
main_frame.grid_rowconfigure(0, weight=1)
main_frame.grid_columnconfigure(0, weight=1)
main_frame.grid_columnconfigure(1, weight=1)

# === Linke Seite (Original-Interface) ===
left_frame = tk.Frame(main_frame)
left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

# Ausgabe-Textbox
output_box = scrolledtext.ScrolledText(left_frame, width=50, height=20, state='disabled', wrap='word')
output_box.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")

# Aktuelle UID
uid_label = tk.Label(left_frame, text="UID: ", anchor="w")
uid_label.grid(row=1, column=0, sticky="w", padx=5, pady=2)

# Aktueller Projektname
project_label = tk.Label(left_frame, text="Projektname: ", anchor="w")
project_label.grid(row=2, column=0, sticky="w", padx=5, pady=2)

# Eingabefeld + Button
entry = tk.Entry(left_frame, width=30)
entry.grid(row=3, column=0, padx=5, pady=10, sticky="w")

def send_project_name():
    """
    Sendet Projektnamen vom GUI-Eingabefeld an Arduino.
    
    Wird aufgerufen wenn:
    - "Projekt hinzufügen" Button geklickt wird
    - Enter-Taste im Eingabefeld gedrückt wird
    """
    name = entry.get().strip()
    if name and ser:
        ser.write((name + '\n').encode('utf-8'))
        entry.delete(0, tk.END)

send_button = tk.Button(left_frame, text="Projekt hinzufügen", command=send_project_name)
send_button.grid(row=3, column=1, padx=5)
root.bind('<Return>', lambda event: send_project_name())

# Grid-Konfiguration für linke Seite
left_frame.grid_rowconfigure(0, weight=1)
left_frame.grid_columnconfigure(0, weight=1)

# === Rechte Seite (Projektliste) ===
right_frame = tk.Frame(main_frame)
right_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

# Titel für Projektliste
projects_title = tk.Label(right_frame, text="Bekannte Projekte", font=("Arial", 12, "bold"))
projects_title.grid(row=0, column=0, pady=(0, 10), sticky="w")

# Treeview für Projektliste
columns = ("Projektname", "Status", "Gesamtzeit", "Aktuelle Session")
project_tree = ttk.Treeview(right_frame, columns=columns, show="headings", height=15)

# Spalten konfigurieren
project_tree.heading("Projektname", text="Projektname")
project_tree.heading("Status", text="Status")
project_tree.heading("Gesamtzeit", text="Gesamtzeit")
project_tree.heading("Aktuelle Session", text="Aktuelle Session")

project_tree.column("Projektname", width=150)
project_tree.column("Status", width=80)
project_tree.column("Gesamtzeit", width=100)
project_tree.column("Aktuelle Session", width=120)

project_tree.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

# Scrollbar für Treeview
scrollbar = ttk.Scrollbar(right_frame, orient="vertical", command=project_tree.yview)
scrollbar.grid(row=1, column=1, sticky="ns")
project_tree.configure(yscrollcommand=scrollbar.set)

# Grid-Konfiguration für rechte Seite
right_frame.grid_rowconfigure(1, weight=1)
right_frame.grid_columnconfigure(0, weight=1)

# === Hilfsfunktionen für Zeitformatierung ===
def format_time(seconds):
    """
    Formatiert Sekunden zu HH:MM:SS Format.
    
    Args:
        seconds (float): Zeit in Sekunden
        
    Returns:
        str: Formatierte Zeit als "HH:MM:SS"
    """
    if seconds < 0:
        return "00:00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def clean_project_name(project_name):
    """
    Entfernt UID-Informationen aus Projektnamen.
    
    Arduino sendet manchmal Projektnamen mit UID-Suffix im Format "Name (UID: XXXXXXXX)".
    Diese Funktion extrahiert nur den eigentlichen Projektnamen.
    
    Args:
        project_name (str): Projektname (möglicherweise mit UID)
        
    Returns:
        str: Bereinigter Projektname ohne UID
    """
    if " (UID: " in project_name:
        return project_name.split(" (UID: ")[0]
    return project_name

def update_project_display():
    """
    Aktualisiert die Projektliste in der GUI.
    
    Berechnet für jedes Projekt:
    - Aktuellen Status (Läuft/Pausiert)
    - Gesamtzeit (inklusive aktueller Session)
    - Aktuelle Session-Zeit
    
    Wird regelmäßig vom Timer aufgerufen für Live-Updates.
    """
    # Alle Items löschen
    for item in project_tree.get_children():
        project_tree.delete(item)
    
    current_time = time.time()
    
    # Projekte hinzufügen
    for project_name, data in projects.items():
        status = "Läuft" if data['is_running'] else "Pausiert"
        
        # Gesamtzeit berechnen
        total_time = data['total_time']
        if data['is_running'] and data['start_time'] is not None:
            # Aktuelle Session zur Gesamtzeit hinzufügen
            current_session_duration = current_time - data['start_time']
            total_display_time = total_time + current_session_duration
        else:
            total_display_time = total_time
        
        total_time_str = format_time(total_display_time)
        
        # Aktuelle Session-Zeit berechnen
        if data['is_running'] and data['start_time'] is not None:
            current_session = current_time - data['start_time']
            session_time = format_time(current_session)
        else:
            session_time = "00:00:00"
        
        project_tree.insert("", "end", values=(project_name, status, total_time_str, session_time))

def add_or_update_project(project_name, action):
    """
    Verwaltet Projekt-Lifecycle basierend auf Arduino-Events.
    
    Diese zentrale Funktion verarbeitet alle projektbezogenen Aktionen:
    - hinzugefügt: Neues Projekt erstellen
    - gestartet: Projekt starten (andere automatisch pausieren)
    - pausiert: Projekt pausieren und Zeit akkumulieren
    - geloescht: Projekt löschen (laufende Zeit vorher speichern)
    
    Args:
        project_name (str): Name des Projekts (wird bereinigt)
        action (str): Aktion ("hinzugefügt", "gestartet", "pausiert", "geloescht")
    """
    current_time = time.time()
    
    # Projektname bereinigen (UID entfernen falls vorhanden)
    clean_name = clean_project_name(project_name)
    
    # Debug-Ausgabe
    print(f"Action: {action} für Projekt: '{project_name}' -> bereinigt: '{clean_name}'")
    
    if action == "hinzugefügt":
        if clean_name not in projects:
            projects[clean_name] = {
                'start_time': None,
                'total_time': 0,
                'is_running': False
            }
            print(f"Projekt {clean_name} hinzugefügt")
    
    elif action == "gestartet":
        # Alle anderen Projekte pausieren
        for proj_name, proj_data in projects.items():
            if proj_data['is_running'] and proj_data['start_time'] is not None:
                session_duration = current_time - proj_data['start_time']
                proj_data['total_time'] += session_duration
                proj_data['is_running'] = False
                proj_data['start_time'] = None
                print(f"Projekt {proj_name} automatisch pausiert (Session: {session_duration:.1f}s)")
        
        # Projekt erstellen falls es nicht existiert, dann starten
        if clean_name not in projects:
            projects[clean_name] = {
                'start_time': current_time,
                'total_time': 0,
                'is_running': True
            }
            print(f"Neues Projekt {clean_name} erstellt und gestartet")
        else:
            projects[clean_name]['start_time'] = current_time
            projects[clean_name]['is_running'] = True
            print(f"Projekt {clean_name} gestartet um {current_time}")
    
    elif action == "pausiert":
        if clean_name in projects and projects[clean_name]['is_running']:
            if projects[clean_name]['start_time'] is not None:
                session_duration = current_time - projects[clean_name]['start_time']
                projects[clean_name]['total_time'] += session_duration
                print(f"Session von {session_duration:.1f} Sekunden zu {clean_name} hinzugefügt")
            projects[clean_name]['is_running'] = False
            projects[clean_name]['start_time'] = None
            print(f"Projekt {clean_name} pausiert, Gesamtzeit: {projects[clean_name]['total_time']:.1f}s")
    
    elif action == "geloescht":
        if clean_name in projects:
            # Wenn das Projekt läuft, erst stoppen und Zeit hinzufügen
            if projects[clean_name]['is_running']:
                if projects[clean_name]['start_time'] is not None:
                    session_duration = current_time - projects[clean_name]['start_time']
                    projects[clean_name]['total_time'] += session_duration
                    print(f"Laufendes Projekt gestoppt beim Löschen: {session_duration:.1f}s hinzugefügt")
                projects[clean_name]['is_running'] = False
                projects[clean_name]['start_time'] = None
            
            total_time = projects[clean_name]['total_time']
            del projects[clean_name]
            print(f"Projekt '{clean_name}' gelöscht (Gesamtzeit war: {format_time(total_time)})")
        else:
            print(f"Projekt '{clean_name}' zum Löschen nicht gefunden!")
    
    # Debug: Aktueller Zustand aller Projekte
    print("Aktuelle Projekte:")
    for name, data in projects.items():
        print(f"  '{name}': running={data['is_running']}, total={data['total_time']:.1f}s, start={data['start_time']}")
    
    update_project_display()

# === Timer für Live-Updates ===
def update_timer():
    """
    Timer-Callback für regelmäßige GUI-Updates.
    
    Wird alle 1000ms aufgerufen um:
    - Laufende Projektzeiten zu aktualisieren
    - GUI-Anzeige zu refreshen
    
    Verwendet root.after() für Thread-sichere GUI-Updates.
    """
    update_project_display()  # Immer aktualisieren, nicht nur bei laufenden Projekten
    root.after(1000, update_timer)  # Alle 1000ms (1 Sekunde) wiederholen

# === Serielle Kommunikation ===
def read_serial():
    """
    Serielle Kommunikation mit Arduino (läuft in separatem Thread).
    
    Kontinuierliches Lesen der seriellen Daten und Verarbeitung verschiedener
    Nachrichtentypen:
    - "RFID erkannt: UID" - Neue RFID-Karte erkannt
    - "Projekt gestartet: Name" - Projekt wurde gestartet
    - "Projekt pausiert: Name" - Projekt wurde pausiert
    - "Projekt geloescht: Name (Zeit)" - Projekt wurde gelöscht
    - "Projekt hinzugefügt: Name" - Neues Projekt hinzugefügt
    - "Unbekannte UID: UID" - Unbekannte RFID-Karte
    
    Alle GUI-Updates erfolgen thread-sicher über root.after().
    """
    global ser
    buffer = ""

    while running:
        if ser and ser.in_waiting:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if not line:  # Leere Zeile überspringen
                    continue
                    
                buffer += line + "\n"

                # GUI-Ausgabe (Thread-sicher)
                def update_output():
                    output_box.configure(state='normal')
                    output_box.insert(tk.END, line + "\n")
                    output_box.configure(state='disabled')
                    output_box.see(tk.END)
                
                root.after(0, update_output)

                # UID und Projektname erkennen
                if "RFID erkannt:" in line:
                    uid = line.split(": ", 1)[1] if ": " in line else "Unbekannt"
                    root.after(0, lambda: uid_label.config(text="UID: " + uid))
                    
                elif "Projekt gestartet:" in line:
                    pname = line.split(": ", 1)[1] if ": " in line else "Unbekannt"
                    clean_name = clean_project_name(pname)
                    root.after(0, lambda p=clean_name: project_label.config(text="Projektname: " + p))
                    root.after(0, lambda p=pname: add_or_update_project(p, "gestartet"))
                    
                elif "Projekt pausiert:" in line:
                    pname = line.split(": ", 1)[1] if ": " in line else "Unbekannt"
                    clean_name = clean_project_name(pname)
                    root.after(0, lambda p=clean_name: project_label.config(text="Projektname: " + p))
                    root.after(0, lambda p=pname: add_or_update_project(p, "pausiert"))
                    
                elif "Projekt geloescht:" in line:
                    # Extrahiere nur den Projektnamen vor der Zeitangabe in Klammern
                    content = line.split(": ", 1)[1] if ": " in line else "Unbekannt"
                    # Entferne die Zeitangabe in Klammern am Ende (z.B. " (0h 5m 23s)")
                    if " (" in content:
                        pname = content.split(" (")[0]
                    else:
                        pname = content
                    
                    root.after(0, lambda: project_label.config(text="Projektname: (gelöscht)"))
                    root.after(0, lambda p=pname: add_or_update_project(p, "geloescht"))
                    
                elif "Projekt hinzugefügt:" in line:
                    pname = line.split(": ", 1)[1] if ": " in line else "Unbekannt"
                    clean_name = clean_project_name(pname)
                    root.after(0, lambda p=clean_name: project_label.config(text="Projektname: " + p))
                    root.after(0, lambda p=pname: add_or_update_project(p, "hinzugefügt"))
                    
                elif "Unbekannte UID:" in line:
                    uid = line.split(": ", 1)[1] if ": " in line else "Unbekannt"
                    root.after(0, lambda u=uid: uid_label.config(text="UID: " + u))
                    root.after(0, lambda: project_label.config(text="Projektname: (neu)"))
                    
            except Exception as e:
                print(f"Fehler beim Lesen der seriellen Daten: {e}")
        
        time.sleep(0.1)  # Kurze Pause um CPU-Last zu reduzieren

# === Setup COM-Port ===
try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    print(f"Verbunden mit {COM_PORT}")
    thread = threading.Thread(target=read_serial)
    thread.daemon = True
    thread.start()
except Exception as e:
    print("Fehler beim Öffnen des Ports:", e)
    # Für Testing ohne Hardware
    ser = None

# Timer starten
update_timer()

# === Beenden ===
def on_closing():
    """
    Cleanup beim Schließen der Anwendung.
    
    - Stoppt den seriellen Thread
    - Schließt serielle Verbindung
    - Beendet GUI
    """
    global running
    running = False
    if ser and ser.is_open:
        ser.close()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()
