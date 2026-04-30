import asyncio
import websockets
import json
import queue
import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
import traceback
import base64
import os
import threading
import http.server
import socketserver
from functools import partial
import sys
import shutil
import re
from datetime import datetime

import config
import assembly_ai
import groq_prompt
import meshy_generator

# --- GUI IMPORTS ---
import tkinter as tk
from tkinter import scrolledtext

audio_queue = queue.Queue()
stream = None
is_recording = False
is_processing = False
background_tasks = set()
connected_clients = 0

# --- FILE SERVER SETTINGS ---
HTTP_PORT = 8000  # Port for the model file server
MODELS_DIR = os.path.join(os.getcwd(), "models")

# --- GLOBAL GUI REFERENCE ---
dashboard_ui = None


# --- TERMINAL OUTPUT REDIRECTOR FOR GUI ---
class PrintRedirector:
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout

    def write(self, text):
        self.original_stdout.write(text)
        if text.strip() and dashboard_ui:
            dashboard_ui.log(text.strip())

    def flush(self):
        self.original_stdout.flush()


sys.stdout = PrintRedirector(sys.stdout)


# --- DASHBOARD UI CLASS ---
class DashboardUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🎙️ Voice-to-3D Pipeline Dashboard")
        self.root.geometry("850x600")
        self.root.configure(bg="#1e1e1e")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Styles
        self.bg_color = "#1e1e1e"
        self.fg_color = "#d4d4d4"
        self.accent_color = "#007acc"
        self.panel_bg = "#252526"

        # Header Panel
        self.header_frame = tk.Frame(root, bg=self.bg_color)
        self.header_frame.pack(fill=tk.X, padx=15, pady=15)

        self.lbl_status = tk.Label(self.header_frame, text="Status: SERVER ONLINE", font=("Segoe UI", 16, "bold"),
                                   bg=self.bg_color, fg="#4caf50")
        self.lbl_status.pack(side=tk.LEFT)

        self.lbl_clients = tk.Label(self.header_frame, text="Unity Clients Connected: 0", font=("Segoe UI", 12),
                                    bg=self.bg_color, fg="#ffcc00")
        self.lbl_clients.pack(side=tk.RIGHT)

        # Body Frame (Logs & Inventory)
        self.body_frame = tk.Frame(root, bg=self.bg_color)
        self.body_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

        # Logs Panel
        self.log_frame = tk.Frame(self.body_frame, bg=self.bg_color)
        self.log_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        tk.Label(self.log_frame, text="Pipeline Logs & Insights", font=("Segoe UI", 11, "bold"), bg=self.bg_color,
                 fg=self.accent_color).pack(anchor=tk.W, pady=(0, 5))
        self.txt_logs = scrolledtext.ScrolledText(self.log_frame, bg=self.panel_bg, fg=self.fg_color,
                                                  font=("Consolas", 10), bd=0, padx=10, pady=10)
        self.txt_logs.pack(fill=tk.BOTH, expand=True)

        # Inventory Panel
        self.inv_frame = tk.Frame(self.body_frame, bg=self.bg_color, width=250)
        self.inv_frame.pack(side=tk.RIGHT, fill=tk.Y)
        self.inv_frame.pack_propagate(False)  # lock width

        tk.Label(self.inv_frame, text="Saved 3D Models", font=("Segoe UI", 11, "bold"), bg=self.bg_color,
                 fg=self.accent_color).pack(anchor=tk.W, pady=(0, 5))
        self.lst_inventory = tk.Listbox(self.inv_frame, bg=self.panel_bg, fg=self.fg_color, font=("Consolas", 10), bd=0,
                                        highlightthickness=0)
        self.lst_inventory.pack(fill=tk.BOTH, expand=True)

        self.refresh_inventory()

    def log(self, message):
        self.root.after(0, self._insert_log, message)

    def _insert_log(self, message):
        self.txt_logs.insert(tk.END, message + "\n")
        self.txt_logs.see(tk.END)

    def update_status(self, status, color="#4caf50"):
        self.root.after(0, lambda: self.lbl_status.config(text=f"Status: {status}", fg=color))

    def update_clients(self, count):
        self.root.after(0, lambda: self.lbl_clients.config(text=f"Unity Clients Connected: {count}"))

    def refresh_inventory(self):
        def _refresh():
            self.lst_inventory.delete(0, tk.END)
            if os.path.exists(MODELS_DIR):
                files = sorted([f for f in os.listdir(MODELS_DIR) if f.endswith('.glb')], reverse=True)
                for f in files:
                    self.lst_inventory.insert(tk.END, f)

        self.root.after(0, _refresh)

    def on_close(self):
        print("[SERVER] Shutting down...")
        os._exit(0)


def run_http_server():
    """Function to run a simple HTTP server in a separate thread."""
    if not os.path.exists(MODELS_DIR):
        os.makedirs(MODELS_DIR)

    class ResilientHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
        def handle(self):
            try:
                super().handle()
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            except Exception:
                pass

    handler = partial(ResilientHTTPRequestHandler, directory=MODELS_DIR)
    socketserver.ThreadingTCPServer.allow_reuse_address = True

    with socketserver.ThreadingTCPServer(("", HTTP_PORT), handler) as httpd:
        print(f"[HTTP] File Server running at http://{config.SERVER_HOST}:{HTTP_PORT}")
        print(f"[HTTP] Serving files from: {MODELS_DIR}")
        httpd.serve_forever()


async def safe_ws_send(websocket, data):
    try:
        await websocket.send(json.dumps(data))
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[SERVER] ⚠️ WebSocket send error: {e}")


async def call_with_retry(func, *args, max_retries=3, delay=2.0):
    for attempt in range(1, max_retries + 1):
        try:
            return await asyncio.to_thread(func, *args)
        except Exception as e:
            print(f"⚠️ [API ERROR] {func.__name__} failed (Attempt {attempt}/{max_retries}): {e}")
            if attempt == max_retries:
                raise Exception(f"{func.__name__} failed: {e}")
            await asyncio.sleep(delay)


def audio_callback(indata, frames, time, status):
    if status: print(f"[AUDIO WARNING] {status}")
    try:
        audio_queue.put_nowait(indata.copy())
    except Exception as e:
        print(f"[AUDIO ERROR] Failed to queue audio: {e}")


async def process_pipeline(websocket):
    global is_processing
    loop = asyncio.get_running_loop()

    def send_status_sync(message):
        # Update Dashboard Status Text dynamically
        if dashboard_ui:
            dashboard_ui.update_status(message, color="#00bcd4")  # Cyan color for active processing

        async def _send():
            await safe_ws_send(websocket, {"type": "status", "text": message})

        try:
            if not loop.is_closed():
                asyncio.run_coroutine_threadsafe(_send(), loop)
        except Exception as e:
            print(f"⚠️ Thread-safe send error: {e}")

    try:
        print("\n" + "=" * 50)
        print("🚀 STARTING PIPELINE")
        print("=" * 50)

        recording_data = []
        while not audio_queue.empty():
            try:
                recording_data.append(audio_queue.get_nowait())
            except queue.Empty:
                break

        if not recording_data:
            raise Exception("No audio detected. Please speak into the microphone.")

        full_audio = np.concatenate(recording_data, axis=0)
        try:
            write(config.FILENAME, config.SAMPLE_RATE, np.int16(full_audio * 32767))
            print(f"[SERVER] 💾 Audio saved to {config.FILENAME}")
        except Exception as e:
            raise Exception(f"Failed to save audio file to disk: {e}")

        send_status_sync("Transcribing voice...")
        raw_text = await call_with_retry(assembly_ai.upload_and_transcribe, config.FILENAME, send_status_sync)
        await safe_ws_send(websocket, {"type": "transcript", "text": f"Raw Voice: {raw_text}"})

        send_status_sync("Groq: Enhancing Prompt...")
        optimized_prompt = await call_with_retry(groq_prompt.enhance_prompt, raw_text)
        await safe_ws_send(websocket, {"type": "transcript", "text": f"\nAI Prompt: {optimized_prompt}"})

        send_status_sync("Meshy: Generating 3D Model...")
        final_model_path = await call_with_retry(meshy_generator.generate_3d_model, optimized_prompt, send_status_sync)

        # --- ENSURE FILE NAMING & PROPER DIRECTORY SAVING ---
        try:
            if not os.path.exists(MODELS_DIR):
                os.makedirs(MODELS_DIR)

            # Generate descriptive filename based on original voice prompt
            safe_name = re.sub(r'[^a-zA-Z0-9\s]', '', raw_text)
            words = safe_name.strip().split()
            short_name = "_".join(words[:4]) if words else "GeneratedModel"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            proper_filename = f"{short_name}_{timestamp}.glb"

            new_filepath = os.path.join(MODELS_DIR, proper_filename)

            # Move and Rename the file to the MODELS_DIR
            shutil.move(final_model_path, new_filepath)
            final_model_path = new_filepath
            print(f"[SERVER] 📂 Model successfully saved to: {final_model_path}")

            # Refresh GUI Inventory
            if dashboard_ui:
                dashboard_ui.refresh_inventory()

        except Exception as e:
            print(f"⚠️ Failed to rename/move file to models folder: {e}")
        # ---------------------------------------------------

        print(f"[SERVER] 📦 Encoding model for transfer...")
        send_status_sync("Downloading...")
        try:
            with open(final_model_path, "rb") as model_file:
                encoded_string = base64.b64encode(model_file.read()).decode('utf-8')

            print(f"[SERVER] 📤 Sending model to Unity...")
            await safe_ws_send(websocket, {
                "type": "model_ready",
                "text": "Done!",
                "path": os.path.basename(final_model_path),
                "data": encoded_string,
                "url": f"http://{config.SERVER_HOST}:{HTTP_PORT}/{os.path.basename(final_model_path)}"
            })
        except Exception as e:
            raise Exception(f"Failed to encode/transfer model: {e}")

        print("\n" + "=" * 50)
        print(f"🎉 PIPELINE SUCCESS! Model transferred.")
        print("=" * 50)

        if dashboard_ui:
            dashboard_ui.update_status("SERVER ONLINE - Idle", color="#4caf50")

    except Exception as e:
        print(f"\n❌ [PIPELINE ABORTED] {e}")
        await safe_ws_send(websocket, {"type": "error", "text": str(e)})
        if dashboard_ui:
            dashboard_ui.update_status("ERROR - Check Logs", color="#ff5252")
    finally:
        is_processing = False
        print("\n🟢 SERVER READY: Listening for next VR Voice Command...\n")


async def unity_client_handler(websocket):
    global stream, is_recording, is_processing, connected_clients

    connected_clients += 1
    if dashboard_ui:
        dashboard_ui.update_clients(connected_clients)

    print(f"\n[SERVER] 🔗 Unity Client Connected.")
    print("🟢 SERVER READY: Listening for next VR Voice Command...\n")

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue

            action = data.get("action")

            if action == "start":
                if is_processing:
                    await safe_ws_send(websocket, {"type": "error", "text": "Please wait, generating..."})
                    continue

                if not is_recording:
                    print("[SERVER] 🔴 RECORDING STARTED...")
                    if dashboard_ui:
                        dashboard_ui.update_status("RECORDING AUDIO...", color="#ff5252")

                    is_recording = True
                    while not audio_queue.empty():
                        try:
                            audio_queue.get_nowait()
                        except queue.Empty:
                            break
                    try:
                        stream = sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1, callback=audio_callback)
                        stream.start()
                        await safe_ws_send(websocket, {"type": "status", "text": "Listening..."})
                    except Exception as e:
                        is_recording = False
                        await safe_ws_send(websocket, {"type": "error", "text": "Microphone error."})

            elif action == "stop" and is_recording:
                print("[SERVER] ⏹️ RECORDING STOPPED. Handing over to Pipeline...")
                is_recording = False
                is_processing = True
                if stream:
                    try:
                        stream.stop();
                        stream.close()
                    except:
                        pass

                task = asyncio.create_task(process_pipeline(websocket))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)

            elif action == "get_inventory":
                files = [f for f in os.listdir(MODELS_DIR) if f.endswith('.glb')]
                await safe_ws_send(websocket, {"type": "inventory_list", "files": files})

            elif action == "request_file":
                filename = data.get("name")
                file_path = os.path.join(MODELS_DIR, filename)
                if os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        encoded = base64.b64encode(f.read()).decode('utf-8')
                    await safe_ws_send(websocket, {
                        "type": "model_ready",
                        "path": filename,
                        "data": encoded,
                        "url": f"http://{config.SERVER_HOST}:{HTTP_PORT}/{filename}"
                    })

    except websockets.exceptions.ConnectionClosed:
        print("[SERVER] 🔌 Unity disconnected.")
    except Exception as e:
        print(f"[SERVER] ❌ Unexpected handler error: {traceback.format_exc()}")
    finally:
        connected_clients = max(0, connected_clients - 1)
        if dashboard_ui:
            dashboard_ui.update_clients(connected_clients)

        if is_recording and stream:
            try:
                stream.stop();
                stream.close()
            except:
                pass
            is_recording = False


async def start_websocket_server():
    print("=======================================")
    print("  VOICE-TO-3D PIPELINE SERVER STARTED")
    print(f"  WebSocket: ws://{config.SERVER_HOST}:{config.SERVER_PORT}")
    print(f"  File Server: http://{config.SERVER_HOST}:{HTTP_PORT}")
    print("=======================================")
    try:
        async with websockets.serve(unity_client_handler, config.SERVER_HOST, config.SERVER_PORT, max_size=10 ** 8):
            await asyncio.Future()
    except Exception as e:
        print(f"[SERVER FATAL ERROR] Failed to start WebSocket server: {e}")


def run_asyncio_loop():
    """Runs the asyncio WebSocket Server inside a background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_websocket_server())


if __name__ == "__main__":
    try:
        # 1. Start GUI on the Main Thread
        root = tk.Tk()
        dashboard_ui = DashboardUI(root)

        # 2. Start HTTP Server on a Background Thread
        http_thread = threading.Thread(target=run_http_server, daemon=True)
        http_thread.start()

        # 3. Start Asyncio WebSocket Server on a Background Thread
        ws_thread = threading.Thread(target=run_asyncio_loop, daemon=True)
        ws_thread.start()

        # Run Tkinter Event Loop
        root.mainloop()

    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
        os._exit(0)