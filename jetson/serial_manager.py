import serial
import json
import time
import threading
import logging
import re

logger = logging.getLogger(__name__)

class SerialManager:
    def __init__(self, config, packet_queue):
        self.nodes = config.get("nodes", {})
        self.packet_queue = packet_queue
        self.running = False
        self.threads = []

    @staticmethod
    def _extract_json_objects(buffer_text):
        objects = []
        depth = 0
        start = None

        for idx, ch in enumerate(buffer_text):
            if ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(buffer_text[start:idx + 1])
                    start = None

        remainder = ""
        if depth > 0 and start is not None:
            remainder = buffer_text[start:]

        return objects, remainder

    @staticmethod
    def _salvage_packet(raw_json, node_name):
        rssi_match = re.search(r'"rssi"\s*:\s*(-?\d+)', raw_json)
        mac_match = re.search(r'"mac"\s*:\s*"([0-9a-fA-F:]{11,17})"', raw_json)
        seq_match = re.search(r'"seq"\s*:\s*(\d+)', raw_json)
        ie_match = re.search(r'"ie"\s*:\s*"([0-9a-fA-F]+)"', raw_json)

        if not rssi_match or not mac_match:
            return None

        packet = {
            "node": node_name,
            "node_label": node_name,
            "mac": mac_match.group(1).lower(),
            "rssi": int(rssi_match.group(1)),
        }

        if seq_match:
            packet["seq"] = int(seq_match.group(1))
        if ie_match:
            packet["ie"] = ie_match.group(1).lower()

        return packet

    def _read_serial(self, node_name, port):
        rx_buffer = ""
        while self.running:
            try:
                with serial.Serial(port, 115200, timeout=1) as ser:
                    logger.info(f"Connected to {node_name} on {port}")
                    while self.running:
                        chunk = ser.read(ser.in_waiting or 1)
                        if not chunk:
                            continue

                        rx_buffer += chunk.decode("utf-8", errors="ignore")
                        objects, rx_buffer = self._extract_json_objects(rx_buffer)

                        # Keep bounded memory when the stream includes non-JSON noise.
                        if len(rx_buffer) > 4096:
                            rx_buffer = rx_buffer[-1024:]

                        for raw_json in objects:
                            try:
                                packet = json.loads(raw_json)
                                packet["esp_timestamp"] = packet.get("timestamp", 0)
                                packet["jetson_timestamp"] = time.time()
                                packet["node"] = node_name
                                self.packet_queue.put(packet)
                            except json.JSONDecodeError:
                                salvaged = self._salvage_packet(raw_json, node_name)
                                if salvaged:
                                    salvaged["esp_timestamp"] = 0
                                    salvaged["jetson_timestamp"] = time.time()
                                    self.packet_queue.put(salvaged)
                                else:
                                    logger.warning(f"Malformed JSON from {node_name}: {raw_json[:180]}")
            except serial.SerialException:
                if self.running:
                    logger.warning(f"Serial disconnected for {node_name} on {port}, retrying...")
                    time.sleep(2)

    def start(self):
        if self.running:
            return
        self.running = True
        self.threads = []
        for node_name, node_info in self.nodes.items():
            t = threading.Thread(target=self._read_serial, args=(node_name, node_info["port"]), daemon=True)
            self.threads.append(t)
            t.start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        for t in self.threads:
            t.join(timeout=2)
        self.threads = []