import time
import psutil

class TelemetryManager:
    def __init__(self, queue_capacity, replay_mode=False):
        self.replay_mode = replay_mode
        self.processed_packets = 0
        self.dropped_packets = 0
        self.state = {
            "nodes": {},
            "ambient_zones": {},
            "pipeline": {
                "queue_depth": 0,
                "queue_capacity": queue_capacity,
                "dropped_packets": 0,
                "processed_packets": 0,
                "processing_latency_ms": 0.0,
                "replay_mode": replay_mode,
                "websocket_clients": 0
            },
            "host": {"cpu_utilization": 0.0, "ram_utilization_mb": 0}
        }

    def update_node(self, name, connected, packet_count, last_packet_time, fw="0.0.0", uptime=0, temp=0.0):
        now = time.time()
        self.state["nodes"][name] = {
            "connected": connected,
            "firmware_version": fw,
            "uptime_seconds": uptime,
            "temperature_c": round(temp, 1),
            "last_packet_ms": int((now - last_packet_time) * 1000) if last_packet_time else -1,
            "packet_count": packet_count
        }

    def increment_processed(self):
        self.processed_packets += 1

    def update_ambient_zones(self, zone_metrics):
        self.state["ambient_zones"] = zone_metrics

    def update_pipeline(self, queue_depth, dropped, latency, clients_count):
        self.dropped_packets = dropped
        self.state["pipeline"].update({
            "queue_depth": queue_depth,
            "dropped_packets": self.dropped_packets,
            "processed_packets": self.processed_packets,
            "processing_latency_ms": round(latency * 1000, 2),
            "websocket_clients": clients_count
        })

    def set_replay_mode(self, replay_mode):
        self.replay_mode = bool(replay_mode)
        self.state["pipeline"]["replay_mode"] = self.replay_mode

    def get_snapshot(self):
        self.state["host"].update({
            "cpu_utilization": psutil.cpu_percent(),
            "ram_utilization_mb": int(psutil.virtual_memory().used / (1024 * 1024))
        })
        now = time.time()
        return {
            "protocol": "invisible4eyes.telemetry",
            "version": "1.0.0",
            "type": "diagnostics_snapshot",
            "observation_time": now,
            "publish_time": time.time(),
            "payload": self.state
        }