import mido
from pythonosc import udp_client
import threading
import time
import json
from websocket import create_connection
from threading import Lock
import logging
import socket
import signal



# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Global variables

running = True
tempo = 78
memorySpan = 0  # default value (OneBar)
print(memorySpan)
sensoryMemoryDivider = 8
sensoryMemory = ((60 / tempo) / sensoryMemoryDivider)*memorySpan
sMCapacity = []
sMCapacity_lock = Lock()
clickTaken = 0
number = None  # Initialize to None or a default value
note_timestamps = {}
takenJSTon = 0  # For tracking JS Tonal key
midi_notes_by_port = {}
sMCapacity_by_port = {}
countNotes_by_port = {}
scale9401 = set()
firstNotescale = None
scale9401_lock = Lock()
last_bar_reset_time = 0  # Tracks when last barReset occurred
# --- at globals (defaults) ---
numerator = 4

def push_tempo_to_websocket(new_tempo: float):
    try:
        if ws and ws.connected:
            ws.send(json.dumps({"type": "updateState", "tempo": float(new_tempo)}))
    except Exception as e:
        print(f"send tempo to ws failed: {e}")



# Initialize OSC client
client = udp_client.SimpleUDPClient("127.0.0.1", 11000)

clearArrayNumber = 1  # Global variable to track array clearing status



midi_notes_by_port = {
    "7401": [],
    "9401": []
}
sMCapacity_by_port = {
    "7401": [],
    "9401": []
}
countNotes_by_port = {
    "7401": [0] * 12,
    "9401": [0] * 12
}

def send_bar_to_websocket(bar_value: int):
    try:
        if ws and ws.connected:
            ws.send(json.dumps({"type": "ablBar", "value": int(bar_value)}))
    except Exception as e:
        print(f"❌ Failed to send bar: {e}")



def reset_clear_array():
    global clearArrayNumber, countNotes
    clearArrayNumber = 0  # Set the variable to 0
    countNotes = [0] * 12  # Reset countNotes to all zeros
    print(f"clearArrayNumber set to {clearArrayNumber}") 
    print(f"Updated countNotes: {countNotes}")


# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    global running
    print("Exiting program...")
    running = False
    if ws:
        ws.close()
    if UDPServerSocket:
        UDPServerSocket.close()
    time.sleep(1)  # Allow threads to exit cleanly

def reconnect_websocket():
    global ws
    try:
        ws = create_connection("ws://localhost:8080")
        print("WebSocket reconnected successfully.")
    except Exception as e:
        print(f"Failed to reconnect WebSocket: {e}")

import json

def listen_to_websocket(ws):
    """Listen to WebSocket messages and update global variables."""
    global tempo, sensoryMemory, clickTaken, clearArrayNumber, countNotes, incomingBpm
    global takenJSTon, memorySpan, last_bar_reset_time, numerator

    while True:
        try:
            message = ws.recv()

            # Güvenli JSON parse: JSON değilse sessizce geç
            try:
                data = json.loads(message)
            except Exception:
                continue

            # 'type' alanı yoksa sessizce geç
            msg_type = data.get('type')
            if not msg_type:
                continue

            # JS'ten gelebilen ve backend'in işlemeyeceği mesaj tiplerini sessizce yut
            if msg_type in ('midi_note',):
                # Örn. {"type":"midi_note","note_number":60,"note_name":"C4"}
                # Backend bu çerçeveyi işlemiyor; uyarı basmadan geç.
                continue

            elif msg_type == 'updateTempo':
                tempo = float(data.get('value', 60))
                # Ableton'a doğrudan tempo gönder
                client.send_message("/live/song/set/tempo", tempo)
                # sensoryMemory'yi güncelle
                sensoryMemory = compute_sensory_memory(tempo, memorySpan, numerator, sensoryMemoryDivider)
                print(f"✅ Updated tempo: {tempo}, Updated sensoryMemory: {sensoryMemory:.3f} s")
                
            elif msg_type == 'tapTempo':
                # A) LiveOSC kullanıyorsan (11000): doğrudan tap komutu
                client.send_message("/live/song/tap_tempo", [])
                print("🖱️ Tap tempo sent to Ableton.")



            elif msg_type == 'startPlaying':
                client.send_message("/live/song/start_playing", [])
                print("🎵 Ableton playback started!")

            elif msg_type == 'stopPlaying':
                client.send_message("/live/song/stop_playing", [])
                print("🛑 Ableton playback stopped!")
                
            elif msg_type == "setSchedule":
                # 1) Bar/Beat'i al
                try:
                    setBar  = int(data.get("bar", 1))
                    setBeat = int(data.get("beat", 1))
                except Exception:
                    print("❌ Invalid bar/beat in setSchedule")
                    return

                # 2) Track/clip: gelmezse 2. track'in 1. slotunu hedefle (0-based: 1,0)
                def safe_int(v, default):
                    try:
                        return int(v)
                    except Exception:
                        return default
                track_i = safe_int(data.get("track"), 1)  # ← default = 1 (2. track)
                clip_i  = safe_int(data.get("clip"),  0)  # ← default = 0 (ilk clip slot)

                # 3) Sınırlar
                setBar  = max(1, setBar)
                setBeat = max(1, setBeat)

                # 4) 1 bar kaç beat? (numerator güncel tutuluyor)
                try:
                    bpb = max(1, int(numerator))
                except Exception:
                    bpb = 4

                # 5) Bar/Beat → mutlak beat (quarter-note) konumu
                start_beats = float((setBar - 1) * bpb + (setBeat - 1))

                print(f"🟡 Received Schedule: bar={setBar}, beat={setBeat}, track={track_i}, clip={clip_i}")

                try:
                    # Clip View'deki Start alanını değiştir
                    # /live/clip/set/start_marker <track_index> <clip_index> <start_in_beats>
                    client.send_message("/live/clip/set/start_marker", [track_i, clip_i, start_beats])

                    # Transport'u aynı konuma taşı (Play oradan başlasın)
                    # /live/song/set/current_song_time <beats>
                    client.send_message("/live/song/set/current_song_time", start_beats)

                    print(f"🎯 Clip Start → {setBar}.{setBeat}.1 (={start_beats} beats), transport moved.")
                except Exception as e:
                    print(f"❌ OSC setSchedule failed: {e}")






            elif msg_type == 'updateNumerator':
                numerator = int(data.get('value', 4))
                # LiveOSC /live/song/set/signature_numerator liste bekler
                client.send_message("/live/song/set/signature_numerator", [numerator])
                # Meter bar uzunluğunu değiştirdiği için sensoryMemory yeniden hesaplanır
                sensoryMemory = compute_sensory_memory(tempo, memorySpan, numerator, sensoryMemoryDivider)
                print(f"🎼 Ableton numerator set to {numerator}")
                print(f"🧠 sensoryMemory recalculated (numerator): {sensoryMemory:.3f} s")

            elif msg_type == 'updateDenominator':
                value = int(data.get('value', 4))
                # LiveOSC /live/song/set/signature_denominator liste bekler
                client.send_message("/live/song/set/signature_denominator", [value])
                print(f"🎼 Ableton denominator set to {value}")

            elif msg_type == 'updateBpm':
                incomingBpm = round(float(data.get('value', 0)), 3)
                tempo = incomingBpm
                # LiveOSC tempo set genelde sayı (float) alır; liste sarmaya gerek yok
                client.send_message("/live/song/set/tempo", tempo)
                # tempo değişti, sensoryMemory’yi tekrar hesapla
                sensoryMemory = compute_sensory_memory(tempo, memorySpan, numerator, sensoryMemoryDivider)
                # print(f"🎼 Ableton tempo updated to: {tempo}")

            elif msg_type == 'clickState':
                clickTaken = int(data.get('value', 0))
                print(f"✅ Updated clickTaken state: {clickTaken}")
                handle_metronome_state()

            elif msg_type == 'clearRequest':
                print("🔥 Processing clearRequest...")
                clearArrayNumber = 0
                countNotes = [0] * 12
                print(f"✅ clearArrayNumber set to {clearArrayNumber}")
                print(f"✅ Updated countNotes: {countNotes}")

            elif msg_type == 'keyIndUpdate':
                takenJSTon = data.get('value')
                print(f"🎹 Updated takenJSTon: {takenJSTon}")

            elif msg_type == 'updateMemorySpan':
                try:
                    memorySpan = int(data.get('value', 32))
                    sensoryMemory = compute_sensory_memory(tempo, memorySpan, numerator, sensoryMemoryDivider)
                    print(f"🧠 WebSocket received memorySpan: {memorySpan}")
                    print(f"🧠 sensoryMemory recalculated (span): {sensoryMemory:.3f} s")
                except Exception as e:
                    print(f"❌ Error setting memorySpan: {e}")

            elif msg_type == 'eeg_sample':
                # {"type":"eeg_sample","eeg":[...8 ch...],"accel":[x,y,z]}
                # Burada sadece alındığını doğruluyoruz; ayrıntı log basmıyoruz.
                pass

            elif msg_type == 'barReset':
                print("📩 WebSocket → barReset mesajı alındı.")
                with sMCapacity_lock, scale9401_lock, midi_notes_lock:
                    sMCapacity.clear()
                    scale9401.clear()
                    midi_notes.clear()
                    midi_notes_by_port["7401"] = []
                    midi_notes_by_port["9401"] = []
                    sMCapacity_by_port["7401"] = []
                    sMCapacity_by_port["9401"] = []
                    countNotes_by_port["7401"] = [0] * 12
                    countNotes_by_port["9401"] = [0] * 12
                    firstNotescale = None
                last_bar_reset_time = time.time()
                print("🧹 base.py: Tüm MIDI ve sMCapacity yapıları temizlendi.")

            else:
                # Tanınmayan tipler için uyarı basmıyoruz; sessizce geç
                # print(f"⚠️ Unknown WebSocket message type: {msg_type}")
                pass

        except Exception as e:
            # JSON parse hataları yukarıda sessizce atlandı; burası bağlantı hataları vb. için
            print(f"❌ WebSocket error: {e}")
            break




# --- Meter-aware sensory memory calculator (fixed signature) ---
def compute_sensory_memory(tempo_val, memory_span_val, numerator_val, divider_val):
    """
    sensoryMemory'yi saniye cinsinden döndürür.
    - 8  (OneBeat)   -> 1 beat
    - 16 (TwoBeats)  -> 2 beat
    - 32 (OneBar)    -> numerator kadar beat
    - 64 (TwoBars)   -> 2 * numerator kadar beat
    - Diğerleri      -> legacy: ((60/tempo)/divider) * memory_span
    """
    try:
        t = float(tempo_val)
        if t <= 0:
            return 0.0
        if memory_span_val == 32:
            beats = max(1, int(numerator_val))
            return (60.0 / t) * beats
        elif memory_span_val == 64:
            beats = max(1, 2 * int(numerator_val))
            return (60.0 / t) * beats
        elif memory_span_val == 8:
            return (60.0 / t) * 1
        elif memory_span_val == 16:
            return (60.0 / t) * 2
        else:
            return ((60.0 / t) / float(divider_val)) * float(memory_span_val)
    except Exception:
        return 0.0


# OSC communication for metronome state
def handle_metronome_state():
    """Update metronome state based on clickTaken."""
    if clickTaken == 1:
        client.send_message("/live/song/set/metronome", 1)
        print("Metronome turned ON in Ableton.")
    elif clickTaken == 0:
        client.send_message("/live/song/set/metronome", 0)
        print("Metronome turned OFF in Ableton.")

def send_state_to_websocket():
    global tempo, sMCapacity, sensoryMemory, ws, midi_notes
    current_time = time.time()

    with sMCapacity_lock, midi_notes_lock:
        if number is not None and number != -999:
            mod_number = number % 12
            last_received_time = note_timestamps.get(mod_number, None)
            if last_received_time is None or (current_time - last_received_time) >= sensoryMemory:
                if mod_number not in sMCapacity:
                    sMCapacity.append(mod_number)
                    sMCapacity.sort()
                note_timestamps[mod_number] = current_time

        # Merge notes from both port-specific and global lists
        all_midi_notes = (
            midi_notes + 
            midi_notes_by_port.get("7401", []) +
            midi_notes_by_port.get("9401", [])
        )
        midi_note_names = [midi_note_to_name(note) for note in all_midi_notes]

        # Compose complete state
        state = {
            "type": "updateState",
            "tempo": tempo,
            "sensoryMemory Duration": sensoryMemory,
            "sMCapacity": sorted(sMCapacity),
            "sMCapacity_7401": sorted(sMCapacity_by_port.get("7401", [])),
            "sMCapacity_9401": sorted(sMCapacity_by_port.get("9401", [])),
            "midi_notes": midi_note_names
        }

        try:
            if ws and ws.connected:
                ws.send(json.dumps(state))
                print(f"Sent: {json.dumps(state, indent=2)}")
            else:
                print("WebSocket is not connected. Attempting to reconnect...")
                reconnect_websocket()
        except Exception as e:
            print(f"Error sending state: {e}")
            reconnect_websocket()



from mido import Message


def udp_listener():
    """Listen for incoming UDP messages and parse manually for MIDI messages and int values."""
    import re
    global number

    while running:
        try:
            bytesAddressPair = UDPServerSocket.recvfrom(bufferSize)
            data = bytesAddressPair[0]

            # --- MIDI (3'lü byte paketleri) ---
            i = 0
            while i + 2 < len(data):
                status = data[i]
                note = data[i + 1]
                velocity = data[i + 2]

                if 0x80 <= status <= 0xEF:
                    try:
                        midi_msg = Message.from_bytes(data[i:i+3])
                        print(f"🎹 MIDI from UDP: {midi_msg}")

                        if midi_msg.type == 'note_on' and midi_msg.velocity > 0:
                            note_timestamps[midi_msg.note] = time.time()
                            send_midi_note_to_websocket(midi_msg.note)
                    except Exception as midi_error:
                        print(f"⚠️ Invalid MIDI: {data[i:i+3]} → {midi_error}")
                i += 3

            # --- BAR PARSING (metin + 4-byte int için dayanıklı) ---
            bar_sent = False

            # 1) Metin olarak dene ("/bar 12", "1. 1. 1", "1 1 1" vb.)
            try:
                txt = data.decode("utf-8", errors="ignore").strip()
                if txt:
                    # Önce /bar {num}
                    m = re.search(r'/bar\s+(\d+)', txt)
                    if m:
                        bar_val = int(m.group(1))
                        send_bar_to_websocket(bar_val)
                        print(f"🧾 Parsed BAR (/bar): {bar_val}")
                        bar_sent = True
                    else:
                        # İlk görülen sayıyı bar kabul et (örn. "1. 1. 1")
                        m = re.search(r'(\d+)', txt)
                        if m:
                            bar_val = int(m.group(1))
                            send_bar_to_websocket(bar_val)
                            print(f"🧾 Parsed BAR (text): {txt} → {bar_val}")
                            bar_sent = True
            except Exception as e:
                print(f"⚠️ Text decode failed: {e}")

            # 2) Olmadıysa son 4 baytı signed int olarak dene
            if not bar_sent and len(data) >= 4:
                raw_data = data[-4:]
                number = int.from_bytes(raw_data, byteorder='big', signed=True)
                if number != -999:
                    send_bar_to_websocket(number)
                    print(f"Received signed integer (bar): {number}")
                    bar_sent = True
                else:
                    print("Ignored -999 value")

            # --- Mevcut genel state gönderimi (varsa) ---
            try:
                send_state_to_websocket()
            except Exception as e:
                print(f"⚠️ send_state_to_websocket error: {e}")

        except Exception as e:
            print(f"UDP listener error: {e}")








# Manage sM capacity
def manage_sm_capacity():
    global sMCapacity
    while True:
        time.sleep(sensoryMemory)
        with sMCapacity_lock:
            sMCapacity.clear()

sm_capacity_thread = threading.Thread(target=manage_sm_capacity)
sm_capacity_thread.daemon = True
sm_capacity_thread.start()

def manage_scale9401():
    global scale9401
    while True:
        time.sleep(sensoryMemory)
        with scale9401_lock:
            scale9401.clear()
            #print("🧹 scale9401 cleared.")

scale9401_thread = threading.Thread(target=manage_scale9401)
scale9401_thread.daemon = True
scale9401_thread.start()


# Manage Ableton tempo lock
#def lock_ableton_tempo():
   # while True:
      #  client.send_message("/live/song/set/tempo", tempo)
       # time.sleep(1)

##tempo_lock_thread = threading.Thread(target=lock_ableton_tempo)
#tempo_lock_thread.daemon = True
#tempo_lock_thread.start()

# Store incoming MIDI notes
midi_notes = []
midi_notes_lock = Lock()

# Function to convert MIDI note number to note name and octave
def midi_note_to_name(midi_note):
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    note_name = note_names[midi_note % 12]
    octave = (midi_note // 12) - 1  # MIDI note 60 is C4
    return f"{note_name}{octave}"

def detect_chord(mod12Bass, sMCapacity_sorted):
    """Detects if the current notes form a C Major chord."""
    if mod12Bass == 0 and all(note in sMCapacity_sorted for note in [0, 4, 7]):
        chord = "C Major"
        print(f"Detected chord: {chord}")
    else:
        chord = "Unknown"
        print("No recognized chord detected.")
    return chord

# Example usage in the script
mod12Bass = 0  # This should be dynamically updated based on the bass note
with sMCapacity_lock:
    sMCapacity_sorted = sorted(sMCapacity)  # Ensure it's sorted before checking
    detected_chord = detect_chord(mod12Bass, sMCapacity_sorted)

# Function to send an individual MIDI note via WebSocket
def send_midi_note_to_websocket(note):
    """Send a single MIDI note number via WebSocket."""
    global ws
    note_name = midi_note_to_name(note)
    
    message = {
        "type": "midi_note",
        "note_number": note,
        "note_name": note_name
    }

    try:
        if ws and ws.connected:
            ws.send(json.dumps(message))
            print(f"Sent MIDI note: {json.dumps(message, indent=2)}")
        else:
            print("WebSocket is not connected. Attempting to reconnect...")
            reconnect_websocket()
    except Exception as e:
        print(f"Error sending MIDI note: {e}")
        reconnect_websocket()

def pretty_print_state(state_dict):
    print("\n📊 [Güncel Sistem Durumu]")
    print(f"  🎼 Tempo: {state_dict['tempo']} BPM")
    print(f"  🕒 Sensory Memory: {state_dict['sensoryMemory Duration']:.3f} s")
    print(f"  🎵 sMCapacity (mod 12): {state_dict['sMCapacity']}")
    print(f"  🎸 Bass Note: {state_dict['bassNote']} (mod12: {state_dict['mod12Bass']})")
    print(f"  🎻 Soprano Note: {state_dict['sopNote']} (mod12: {state_dict['mod12Sop']})")
    print(f"  🎹 Actual MIDI Notes: {state_dict['Actual MIDI notes']}")
    print(f"  🎶 Note Names: {state_dict['Actual MIDI note names']}")
    print(f"  📊 Total Count: {state_dict['Total Count']}")
    print(f"  🔁 scale9401: {state_dict['scale9401']}")
    print(f"  🎯 First Note in Scale: {state_dict['firstNotescale']}\n")

# Initialize global countNotes array with 12 zeros
countNotes = [0] * 12

def listen_to_midi(input_name, port_label=None):
    global sMCapacity, midi_notes, ws, countNotes, takenJSTon, firstNotescale
    with mido.open_input(input_name) as inport:
        for msg in inport:
            if msg.type == 'note_on' and msg.velocity > 0:
                if port_label:
                    print(f"🎹 [{port_label}] Received MIDI: {msg}")
                else:
                    print(f"🎹 Received MIDI: {msg}")
                    
                with sMCapacity_lock, midi_notes_lock:
                    note_mod = msg.note % 12

                    # 🔐 Conditional countNotes increment logic
                    if takenJSTon in [str(i) for i in range(12)]:
                        shift = int(takenJSTon)
                        mapped_index = (note_mod - shift) % 12
                        countNotes[mapped_index] += 1
                        print(f"✅ takenJSTon is {takenJSTon} — Mapped pitch class {note_mod} to {mapped_index}, countNotes: {countNotes}")

                    if note_mod not in sMCapacity:
                        sMCapacity.append(note_mod)

                    if msg.note not in midi_notes:
                        midi_notes.append(msg.note)

                # ✅ ADDITIONAL LOGIC FOR scale9401
                if port_label == "9401":
                    try:
                        if takenJSTon is not None and str(takenJSTon).isdigit():
                            shifted_note = (msg.note % 12 - int(takenJSTon)) % 12
                            with scale9401_lock:
                                prev_empty = len(scale9401) == 0
                                scale9401.add(shifted_note)
                                if prev_empty and scale9401:
                                    firstNotescale = shifted_note
                                    print(f"🎯 First note in scale9401: {firstNotescale}")
                        else:
                            print("⚠️ takenJSTon is not valid.")
                    except Exception as e:
                        print(f"⚠️ Error processing scale9401: {e}")

                send_midi_note_to_websocket(msg.note)

                sorted_notes = sorted(midi_notes)
                sMCapacity_sorted = sorted(set(n % 12 for n in sorted_notes),
                                           key=lambda x: sorted_notes.index(min(n for n in sorted_notes if n % 12 == x)))

                if midi_notes:
                    bass_note = min(midi_notes)
                    sop_note = max(midi_notes)
                    bass_note_name = midi_note_to_name(bass_note)
                    sop_note_name = midi_note_to_name(sop_note)
                    mod12Bass = bass_note % 12
                    mod12Sop = sop_note % 12
                else:
                    bass_note_name, sop_note_name = "None", "None"
                    mod12Bass, mod12Sop = "None", "None"

                # ✅ If scale9401 was cleared externally and is now empty, notify JS with empty state
                if port_label == "9401" and len(scale9401) == 0 and firstNotescale is None:
                    empty_state = {
                        "type": "updateState",
                        "scale9401": [],
                        "firstNotescale": None
                    }
                    try:
                        if ws and ws.connected:
                            ws.send(json.dumps(empty_state))
                            print("📤 Sent empty scale9401 state to WebSocket.")
                    except Exception as e:
                        print(f"❌ Failed to send empty scale9401 state: {e}")

                # ✅ MERGED STATE
                state = {
                    "tempo": tempo,
                    "sensoryMemory Duration": sensoryMemory,
                    "sMCapacity": sMCapacity_sorted,
                    "bassNote": bass_note_name,
                    "sopNote": sop_note_name,
                    "mod12Bass": mod12Bass,
                    "mod12Sop": mod12Sop,
                    "Actual MIDI notes": sorted_notes,
                    "Actual MIDI note names": [midi_note_to_name(n) for n in sorted_notes],
                    "Total Count": countNotes,
                    "scale9401": sorted(list(scale9401)),
                    "firstNotescale": firstNotescale
                }

                try:
                    if ws and ws.connected:
                        ws.send(json.dumps(state))
                        pretty_print_state(state)

                    else:
                        print("WebSocket is not connected. Attempting to reconnect...")
                        reconnect_websocket()
                except Exception as e:
                    print(f"Error sending state: {e}")
                    reconnect_websocket()

# Function to clear midi_notes array periodically
def clear_midi_notes():
    global midi_notes
    while True:
        time.sleep(sensoryMemory)
        with midi_notes_lock:
            midi_notes.clear()
            #print("Cleared MIDI notes.")

# Start the thread to clear midi_notes periodically
clear_midi_thread = threading.Thread(target=clear_midi_notes)
clear_midi_thread.daemon = True
clear_midi_thread.start()


# Initialize WebSocket
try:
    ws = create_connection("ws://localhost:8080")
    print("WebSocket connected successfully.")
except Exception as e:
    print(f"WebSocket connection failed: {e}")
    ws = None

if ws:
    websocket_thread = threading.Thread(target=listen_to_websocket, args=(ws,))
    websocket_thread.daemon = True
    websocket_thread.start()


# UDP server setup
localIP = "127.0.0.1"
localPort = 9401
bufferSize = 1024
UDPServerSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
UDPServerSocket.bind((localIP, localPort))
print("UDP Server listening...")

udp_thread = threading.Thread(target=udp_listener)
udp_thread.daemon = True
udp_thread.start()

# MIDI input setup
logging.info("Program started.")
logging.warning("This is a warning message.")
logging.error("This is an error message.")

print("Available MIDI input ports:")
available_ports = mido.get_input_names()
for name in available_ports:
    print(name)

midi_ports_to_listen = {
    "loopMIDI Port 7401 4": "7401",
    "loopMIDI Port 9401 3": "9401"
}

for port_name, label in midi_ports_to_listen.items():
    if port_name in available_ports:
        thread = threading.Thread(target=listen_to_midi, args=(port_name, label))
        thread.start()
        print(f"✅ Listening to {port_name}")
    else:
        print(f"❌ Port '{port_name}' not found.")

# Signal handling
signal.signal(signal.SIGINT, signal_handler)

# Keep program running
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nProgram interrupted. Exiting...")
    ws.close()
