import os
import sys
import base64
import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pygame
import threading
import hashlib
import json
from enum import Enum

MAX_PACKET_SIZE = 64
CURRENT_FILE_INFO = {}

class PacketType(Enum):
    START = 0
    DATA = 1
    END = 2

class CC1101Controller:
    def __init__(self, app):
        self.app = app
        self.ser = None
        self.rx_buffer = {}
        self.current_file = None
        self.transmit_mode = True
        self.connected = False

    def calculate_checksum(self, data):
        return hashlib.md5(data).hexdigest()[:2]

    def encode_packet(self, packet_type, seq_num, total_packets, data, filename=""):
        header = {
            'type': packet_type.name,
            'seq': seq_num,
            'total': total_packets,
            'filename': filename,
            'checksum': self.calculate_checksum(data)
        }
        return base64.b64encode(json.dumps(header).encode() + b'||' + data).decode()

    def decode_packet(self, packet):
        try:
            decoded = base64.b64decode(packet)
            header_str, data = decoded.split(b'||', 1)
            header = json.loads(header_str)
            return header, data
        except Exception as e:
            if self.app.verbose_var.get():
                print(f"Decode error: {e}")
            return None, None

    def connect_serial(self, port):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.ser = serial.Serial(port, 115200, timeout=1)
            self.connected = True
            threading.Thread(target=self.receive_loop, daemon=True).start()
            return True
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect to {port}:\n{str(e)}")
            return False

    def send_command(self, command):
        if self.connected and self.ser:
            try:
                self.ser.write(f"{command}\n".encode())
                if self.app.verbose_var.get():
                    print(f"Sent command: {command}")
            except Exception as e:
                self.app.status_bar.config(text=f"Send error: {e}")

    def receive_loop(self):
        while self.connected and self.ser.is_open:
            try:
                if self.ser.in_waiting:
                    raw = self.ser.readline().decode().strip()
                    if self.app.verbose_var.get():
                        print(f"Raw received: {raw}")
                    
                    if raw.startswith("<DATA|"):
                        packet = raw[6:-1]
                        header, data = self.decode_packet(packet)
                        
                        if header and data:
                            if header['checksum'] != self.calculate_checksum(data):
                                raise ValueError("Checksum mismatch")
                                
                            if header['type'] == 'START':
                                CURRENT_FILE_INFO.clear()
                                CURRENT_FILE_INFO.update({
                                    'name': header['filename'],
                                    'total': header['total'],
                                    'data': []
                                })
                            
                            CURRENT_FILE_INFO['data'].append(data)
                            
                            if len(CURRENT_FILE_INFO['data']) == header['total']:
                                full_data = b''.join(CURRENT_FILE_INFO['data'])
                                decoded = base64.b64decode(full_data)
                                save_path = filedialog.asksaveasfilename(
                                    initialfile=CURRENT_FILE_INFO['name']
                                )
                                with open(save_path, 'wb') as f:
                                    f.write(decoded)
                                self.app.status_bar.config(text=f"File saved: {save_path}")
                                
                    elif raw.startswith("<STATUS|"):
                        self.app.status_bar.config(text=raw[8:-1])
                        
            except Exception as e:
                self.app.status_bar.config(text=f"Receive error: {str(e)}")

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.connected = False

class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.verbose_var = tk.BooleanVar()
        self.status_bar = None
        self.controller = CC1101Controller(self)
        self.title("RF Communication Suite")
        self.geometry("800x600")
        self.setup_ui()
        self.refresh_ports()
        pygame.mixer.init()

    def setup_ui(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Status Bar (initialized first)
        self.status_bar = ttk.Label(self, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Connection Frame
        conn_frame = ttk.LabelFrame(main_frame, text="Connection Settings")
        conn_frame.pack(fill=tk.X, pady=5)
        
        self.port_combo = ttk.Combobox(conn_frame, width=25)
        self.port_combo.grid(row=0, column=0, padx=5, pady=2)
        
        ttk.Button(conn_frame, text="Refresh", command=self.refresh_ports).grid(row=0, column=1, padx=5, pady=2)
        ttk.Button(conn_frame, text="Connect", command=self.toggle_connection).grid(row=0, column=2, padx=5, pady=2)
        
        # RX Ready Button
        rx_frame = ttk.Frame(conn_frame)
        rx_frame.grid(row=0, column=3, padx=5)
        ttk.Button(rx_frame, text="RX Ready", command=self.set_rx_ready).pack()
        
        # Verbose Checkbox
        ttk.Checkbutton(conn_frame, text="Verbose", variable=self.verbose_var).grid(row=0, column=4, padx=5)

        # Radio Configuration
        radio_frame = ttk.LabelFrame(main_frame, text="Radio Configuration")
        radio_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(radio_frame, text="Frequency (MHz):").grid(row=0, column=0, padx=5)
        self.freq_entry = ttk.Entry(radio_frame, width=10)
        self.freq_entry.insert(0, "462.1")
        self.freq_entry.grid(row=0, column=1, padx=5)
        
        self.mode_btn = ttk.Button(radio_frame, text="Switch to RX Mode", command=self.toggle_mode)
        self.mode_btn.grid(row=0, column=2, padx=5)

        # File Transfer Section
        transfer_frame = ttk.LabelFrame(main_frame, text="File Transfer")
        transfer_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.file_list = tk.Listbox(transfer_frame, height=8)
        self.file_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        btn_frame = ttk.Frame(transfer_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)
        
        ttk.Button(btn_frame, text="Add File", command=self.add_file).pack(pady=2, fill=tk.X)
        ttk.Button(btn_frame, text="Send Selected", command=self.send_selected).pack(pady=2, fill=tk.X)
        ttk.Button(btn_frame, text="Clear List", command=self.clear_files).pack(pady=2, fill=tk.X)

    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo['values'] = ports
        if ports:
            self.port_combo.current(0)

    def toggle_connection(self):
        if self.controller.connected:
            self.controller.disconnect()
            self.status_bar.config(text="Disconnected")
            self.port_combo['state'] = 'readonly'
            self.mode_btn['text'] = "Switch to RX Mode"
        else:
            port = self.port_combo.get()
            if port and self.controller.connect_serial(port):
                self.status_bar.config(text=f"Connected to {port}")
                self.port_combo['state'] = 'disabled'
            else:
                self.status_bar.config(text="Connection failed")

    def set_rx_ready(self):
        self.controller.send_command("<RXMODE>")
        self.controller.send_command("<RX_READY>")
        self.status_bar.config(text="Device in receive mode")

    def toggle_mode(self):
        self.controller.transmit_mode = not self.controller.transmit_mode
        mode = "RX" if not self.controller.transmit_mode else "TX"
        self.mode_btn.config(text=f"Switch to {mode} Mode")
        cmd = "<RXMODE>" if mode == "RX" else "<TXMODE>"
        self.controller.send_command(cmd)

    def add_file(self):
        files = filedialog.askopenfilenames()
        for f in files:
            self.file_list.insert(tk.END, f)

    def send_selected(self):
        if not self.controller.connected:
            messagebox.showwarning("Not Connected", "Please connect to a device first")
            return
        
        selected = self.file_list.curselection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select files to send")
            return
        
        file_path = self.file_list.get(selected[0])
        file_name = os.path.basename(file_path)
        
        with open(file_path, "rb") as f:
            file_data = f.read()
        
        b64_data = base64.b64encode(file_data).decode()
        chunks = [b64_data[i:i+MAX_PACKET_SIZE] for i in range(0, len(b64_data), MAX_PACKET_SIZE)]
        total = len(chunks)
        
        self.controller.send_command("<TXMODE>")
        self.controller.send_command(f"<FILE|{file_name}|{total}|{len(file_data)}>")
        
        for i, chunk in enumerate(chunks):
            packet = self.controller.encode_packet(
                PacketType.START if i == 0 else PacketType.DATA,
                i+1,
                total,
                chunk.encode(),
                file_name
            )
            self.controller.send_command(f"<DATA|{packet}>")
            if self.verbose_var.get():
                print(f"Sent packet {i+1}/{total}")
        
        self.controller.send_command(f"<FILE_END|{file_name}>")
        self.status_bar.config(text=f"Completed sending {file_name}")

    def clear_files(self):
        self.file_list.delete(0, tk.END)

if __name__ == "__main__":
    app = Application()
    app.mainloop()
