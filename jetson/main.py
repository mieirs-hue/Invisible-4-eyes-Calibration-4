import time
import json
import math
import queue
import os
import glob
from config import load_config, save_config
from logger import setup_logger
from heartbeat import HeartbeatMonitor
from packet_queue import PacketQueue
from serial_manager import SerialManager
from calibration import Calibration
from aligner import TemporalAligner
from ambient_analyzer import AmbientZoneAnalyzer
from feature_extractor import FeatureExtractor
from tracker import SpatialTracker
from identity import IdentityTracker
from telemetry_manager import TelemetryManager
from web.websocket import WebSocketServer

SCHEMA_VERSION = "1.0.0"


VISUAL_NODE_POSITIONS = {
    "north": (10.0, -5.0),
    "south": (-10.0, 5.0),
    "east": (-10.0, -5.0),
    "west": (10.0, 5.0),
}

VISUAL_CORNER_TO_NODE = {
    "northwest": "east",
    "northeast": "north",
    "southwest": "south",
    "southeast": "west",
}

TRIANGLE_NODE_GROUPS = {
    "T1": ["northwest", "northeast", "southeast"],
    "T2": ["northwest", "southwest", "southeast"],
    "T3": ["northwest", "northeast", "southwest"],
    "T4": ["northeast", "southwest", "southeast"],
}


class ReplayInjector:
    def __init__(self, file_path, playback_speed=1.0, loop=True):
        self.file_path = file_path
        self.playback_speed = max(0.05, float(playback_speed))
        self.loop = bool(loop)
        self.records = []
        self.log_version = "unknown"
        self.index = 0
        self.start_wall_time = 0.0
        self.first_packet_time = 0.0
        self._load_records()

    def _load_records(self):
        if not os.path.exists(self.file_path):
            self.records = []
            return

        loaded = []
        with open(self.file_path, "r", encoding="utf-8") as replay_file:
            for line in replay_file:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    packet = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(packet, dict):
                    continue
                if packet.get("type") == "log_header":
                    self.log_version = str(packet.get("log_version", "unknown"))
                    continue
                if packet.get("node") not in VISUAL_NODE_POSITIONS:
                    continue
                if "rssi" not in packet:
                    continue
                loaded.append(packet)

        self.records = loaded

    def reset(self, now):
        self.index = 0
        self.start_wall_time = now
        if self.records:
            first = self.records[0]
            self.first_packet_time = float(
                first.get("jetson_timestamp")
                or first.get("timestamp")
                or first.get("esp_timestamp")
                or 0.0
            )
        else:
            self.first_packet_time = 0.0

    def is_ready(self):
        return bool(self.records)

    def duration_seconds(self):
        if len(self.records) < 2:
            return 0.0
        first = float(
            self.records[0].get("jetson_timestamp")
            or self.records[0].get("timestamp")
            or self.records[0].get("esp_timestamp")
            or 0.0
        )
        last = float(
            self.records[-1].get("jetson_timestamp")
            or self.records[-1].get("timestamp")
            or self.records[-1].get("esp_timestamp")
            or first
        )
        return max(0.0, last - first)

    def progress_seconds(self):
        if not self.records or self.index <= 0:
            return 0.0
        anchor = self.records[min(self.index - 1, len(self.records) - 1)]
        current = float(
            anchor.get("jetson_timestamp")
            or anchor.get("timestamp")
            or anchor.get("esp_timestamp")
            or self.first_packet_time
        )
        return max(0.0, current - self.first_packet_time)

    def seek_seconds(self, seconds, now):
        if not self.records:
            return
        target_elapsed = max(0.0, float(seconds))
        self.index = 0
        for i, packet in enumerate(self.records):
            packet_time = float(
                packet.get("jetson_timestamp")
                or packet.get("timestamp")
                or packet.get("esp_timestamp")
                or self.first_packet_time
            )
            if (packet_time - self.first_packet_time) >= target_elapsed:
                self.index = i
                break
        else:
            self.index = len(self.records) - 1

        self.start_wall_time = now - (target_elapsed / self.playback_speed)

    def next_packets(self, now, max_packets=300):
        if not self.records:
            return []

        replay_elapsed = (now - self.start_wall_time) * self.playback_speed
        packets = []

        while self.index < len(self.records) and len(packets) < max_packets:
            source_packet = self.records[self.index]
            source_time = float(
                source_packet.get("jetson_timestamp")
                or source_packet.get("timestamp")
                or source_packet.get("esp_timestamp")
                or self.first_packet_time
            )
            packet_elapsed = source_time - self.first_packet_time
            if packet_elapsed > replay_elapsed:
                break

            replay_packet = dict(source_packet)
            replay_packet["replay"] = True
            replay_packet["source_timestamp"] = source_time
            replay_packet["jetson_timestamp"] = now
            packets.append(replay_packet)
            self.index += 1

        if self.index >= len(self.records) and self.loop:
            self.reset(now)

        return packets


def list_available_datasets(base_dir):
    pattern = os.path.join(base_dir, "*.jsonl")
    files = [os.path.basename(path) for path in glob.glob(pattern)]
    return sorted(files)


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _agreement_score(values):
    if not values:
        return 0.0
    mean_val = sum(values) / len(values)
    if mean_val <= 0:
        return 0.0
    variance = sum((value - mean_val) ** 2 for value in values) / len(values)
    std_dev = math.sqrt(variance)
    return clamp(1.0 - (std_dev / mean_val), 0.0, 1.0)


def _build_triangle_metrics(node_strengths, node_packet_hz):
    corner_strengths = {}
    corner_packet_hz = {}

    for corner_id, node_name in VISUAL_CORNER_TO_NODE.items():
        corner_strengths[corner_id] = clamp(float(node_strengths.get(node_name, 0.0)), 0.0, 1.0)
        corner_packet_hz[corner_id] = max(0.0, float(node_packet_hz.get(node_name, 0.0)))

    triangles = {}
    for triangle_id, corners in TRIANGLE_NODE_GROUPS.items():
        strengths = [corner_strengths[corner] for corner in corners]
        packets = [corner_packet_hz[corner] for corner in corners]
        confidence = sum(strengths) / len(strengths)
        agreement = _agreement_score(strengths)
        packet_hz = sum(packets) / len(packets)
        triangles[triangle_id] = {
            "corners": corners,
            "confidence": round(confidence, 3),
            "agreement": round(agreement, 3),
            "packet_hz": round(packet_hz, 2),
        }

    return triangles


def _build_triangle_estimates(node_strengths):
    corner_strengths = {}
    for corner_id, node_name in VISUAL_CORNER_TO_NODE.items():
        corner_strengths[corner_id] = max(0.01, float(node_strengths.get(node_name, 0.0)))

    corner_positions = {
        "northwest": (-10.0, -5.0),
        "northeast": (10.0, -5.0),
        "southwest": (-10.0, 5.0),
        "southeast": (10.0, 5.0),
    }

    estimates = {}
    for triangle_id, corners in TRIANGLE_NODE_GROUPS.items():
        total = sum(corner_strengths[corner] for corner in corners) or 1.0
        x = sum(corner_positions[corner][0] * corner_strengths[corner] for corner in corners) / total
        z = sum(corner_positions[corner][1] * corner_strengths[corner] for corner in corners) / total
        estimates[triangle_id] = [round(x, 3), 3.0, round(z, 3)]

    return estimates


def _build_confidence_ellipsoid(node_strengths, fused_confidence):
    north = clamp(float(node_strengths.get("north", 0.0)), 0.0, 1.0)
    south = clamp(float(node_strengths.get("south", 0.0)), 0.0, 1.0)
    east = clamp(float(node_strengths.get("east", 0.0)), 0.0, 1.0)
    west = clamp(float(node_strengths.get("west", 0.0)), 0.0, 1.0)

    uncertainty_x = 1.0 - ((east + west) / 2.0)
    uncertainty_z = 1.0 - ((north + south) / 2.0)

    axis_x = 0.6 + (uncertainty_x * 3.6)
    axis_z = 0.6 + (uncertainty_z * 3.6)
    axis_y = 0.45 + ((1.0 - fused_confidence) * 1.6)

    ns_delta = north - south
    ew_delta = east - west
    yaw = math.atan2(ns_delta, ew_delta + 1e-6)

    return {
        "axes": [round(axis_x, 3), round(axis_y, 3), round(axis_z, 3)],
        "yaw": round(yaw, 4),
    }


def _compute_node_packet_rates(telemetry_state_nodes, previous_counts, sample_seconds):
    rates = {}
    safe_window = max(0.001, sample_seconds)
    for node_name in VISUAL_NODE_POSITIONS:
        current_count = int(telemetry_state_nodes.get(node_name, {}).get("packet_count", 0))
        previous_count = int(previous_counts.get(node_name, current_count))
        delta_packets = max(0, current_count - previous_count)
        rates[node_name] = delta_packets / safe_window
        previous_counts[node_name] = current_count
    return rates


def estimate_tracking(window_packets, calibrator, node_packet_hz, controls, mode_state):
    node_samples = {node: [] for node in VISUAL_NODE_POSITIONS}

    for packet in window_packets:
        if "status" in packet or "heartbeat" in packet:
            continue

        node_name = packet.get("node")
        if node_name not in node_samples:
            continue

        node_samples[node_name].append(calibrator.calibrate(packet.get("rssi", -100), node_name))

    node_strengths = {}
    for node_name, samples in node_samples.items():
        if samples:
            node_strengths[node_name] = sum(samples) / len(samples)
        else:
            node_strengths[node_name] = 0.0

    if not any(value > 0.0 for value in node_strengths.values()):
        return None

    weighted_nodes = {node: max(0.02, strength) for node, strength in node_strengths.items()}
    weight_total = sum(weighted_nodes.values()) or 1.0

    target_x = sum(weighted_nodes[node] * VISUAL_NODE_POSITIONS[node][0] for node in weighted_nodes) / weight_total
    target_z = sum(weighted_nodes[node] * VISUAL_NODE_POSITIONS[node][1] for node in weighted_nodes) / weight_total

    target_x = clamp(target_x, -12.0, 12.0)
    target_z = clamp(target_z, -7.0, 7.0)

    radii = {
        "northwest": round(clamp(3.0 + (weighted_nodes["east"] * 9.0), 0.5, 12.0), 2),
        "northeast": round(clamp(3.0 + (weighted_nodes["north"] * 9.0), 0.5, 12.0), 2),
        "southwest": round(clamp(3.0 + (weighted_nodes["south"] * 9.0), 0.5, 12.0), 2),
        "southeast": round(clamp(3.0 + (weighted_nodes["west"] * 9.0), 0.5, 12.0), 2),
    }

    ranked_nodes = sorted(weighted_nodes.items(), key=lambda item: item[1], reverse=True)
    top_three = [node for node, _ in ranked_nodes[:3]]
    confidence = clamp(sum(weight for _, weight in ranked_nodes[:3]) / (3.0 or 1.0), 0.0, 1.0)

    triangles = _build_triangle_metrics(node_strengths, node_packet_hz)
    triangle_estimates = _build_triangle_estimates(node_strengths)
    ellipsoid = _build_confidence_ellipsoid(node_strengths, confidence)

    return {
        "id": "human_target",
        "position": [round(target_x, 3), 3.0, round(target_z, 3)],
        "confidence": round(confidence, 3),
        "radii": radii,
        "confirmed_nodes": top_three,
        "node_strengths": {node: round(strength, 4) for node, strength in node_strengths.items()},
        "triangles": triangles,
        "triangle_estimates": triangle_estimates,
        "ellipsoid": ellipsoid,
        "controls": {
            "confidence_threshold": round(float(controls.get("confidence_threshold", 0.82)), 3),
            "rf_gain": round(float(controls.get("rf_gain", 1.0)), 3),
            "replay_active": mode_state.get("state") == "REPLAY",
        },
    }

def main():
    logger = setup_logger()
    logger.info("Starting Invisible 4=eyes pipeline...")
    
    config = load_config("config.yaml")
    
    # Initialize subsystems
    packet_queue = PacketQueue(maxsize=5000)
    heartbeat = HeartbeatMonitor()
    serial_mgr = SerialManager(config, packet_queue)
    
    calibrator = Calibration(config)
    aligner = TemporalAligner(time_window=config["pipeline"]["time_window"])
    zone_map = config.get("zone_map", {
        "north": "Gadget",
        "south": "Gilligan",
        "east": "Kingsman Red",
        "west": "Matrix Green"
    })
    zone_multipliers = config.get("zone_multipliers", {})
    ambient_analyzer = AmbientZoneAnalyzer(calibrator, zone_map, zone_multipliers)
    extractor = FeatureExtractor(calibrator)
    
    spatial_tracker = SpatialTracker(
        eps=config["pipeline"]["dbscan_eps"],
        min_samples=config["pipeline"]["dbscan_min_samples"]
    )
    identity_tracker = IdentityTracker()
    
    telemetry = TelemetryManager(queue_capacity=5000)
    control_messages = queue.Queue()
    config_path = "config.yaml"
    runtime_controls = {
        "rf_gain": 1.0,
        "confidence_threshold": 0.82,
        "node_offsets_db": {node: 0.0 for node in VISUAL_NODE_POSITIONS},
    }
    mode_state = {
        "state": "LIVE",
        "dataset": "recorded_packets.jsonl",
        "playback_speed": 1.0,
        "loop": True,
        "paused": False,
        "position_sec": 0.0,
        "duration_sec": 0.0,
    }
    recording_state = {
        "enabled": True,
        "filename": "recorded_packets.jsonl",
    }
    debug_state = {
        "show_triangles": True,
        "show_node_spheres": True,
    }
    replay_injector = None

    def enqueue_control_message(message):
        control_messages.put(message)

    ws_server = WebSocketServer(
        port=config["pipeline"].get("websocket_port", 8765),
        on_message=enqueue_control_message,
    )
    
    # Optional Data Recorder for replay
    recorder_file = open(recording_state["filename"], "a")
    start_time = time.time()

    def ensure_recording_header(file_handle, file_name):
        if not file_handle or file_handle.closed:
            return
        if os.path.getsize(file_name) > 0:
            return
        header = {
            "type": "log_header",
            "log_version": "1.0.0",
            "schema": SCHEMA_VERSION,
            "created_at": time.time(),
        }
        file_handle.write(json.dumps(header) + "\n")
        file_handle.flush()

    ensure_recording_header(recorder_file, recording_state["filename"])

    def reset_tracking_state():
        nonlocal aligner, spatial_tracker, identity_tracker
        aligner = TemporalAligner(time_window=config["pipeline"]["time_window"])
        spatial_tracker = SpatialTracker(
            eps=config["pipeline"]["dbscan_eps"],
            min_samples=config["pipeline"]["dbscan_min_samples"]
        )
        identity_tracker = IdentityTracker()
        packet_queue.get_all()

    def _broadcast(message_type, payload, now):
        ws_server.broadcast({
            "protocol": "invisible4eyes.telemetry",
            "version": "1.0.0",
            "schema": SCHEMA_VERSION,
            "type": message_type,
            "observation_time": now,
            "publish_time": time.time(),
            "payload": payload,
        })

    def _parse_node_offsets(message):
        offsets = message.get("node_offsets")
        if offsets is None:
            params = message.get("parameters", {})
            offsets = params.get("node_offsets_db", {})
        return offsets if isinstance(offsets, dict) else {}

    def handle_calibration(message, now):
        rf_gain_value = message.get("rf_gain")
        if rf_gain_value is None:
            rf_gain_value = message.get("parameters", {}).get("rf_gain")

        threshold_value = message.get("confidence_threshold")
        if threshold_value is None:
            threshold_value = message.get("parameters", {}).get("confidence_threshold")

        if rf_gain_value is not None:
            runtime_controls["rf_gain"] = float(rf_gain_value)
        if threshold_value is not None:
            runtime_controls["confidence_threshold"] = float(threshold_value)

        for node_name, value in _parse_node_offsets(message).items():
            if node_name in runtime_controls["node_offsets_db"]:
                runtime_controls["node_offsets_db"][node_name] = float(value)

        calibrator.update_runtime_gain(runtime_controls["rf_gain"])
        calibrator.update_runtime_offsets(runtime_controls["node_offsets_db"])

        _broadcast("control_ack", {
            "applied": {
                "rf_gain": runtime_controls["rf_gain"],
                "confidence_threshold": runtime_controls["confidence_threshold"],
                "node_offsets_db": runtime_controls["node_offsets_db"],
            }
        }, now)

    def _normalize_mode_message(message):
        mode = message.get("mode")
        dataset = message.get("dataset")
        playback_speed = message.get("playback_speed")
        loop_value = message.get("loop")
        replay_action = message.get("replay_action")
        seek_sec = message.get("seek_sec")

        if mode is None and isinstance(message.get("mode_config"), dict):
            mode_cfg = message.get("mode_config", {})
            mode = mode_cfg.get("state")
            dataset = mode_cfg.get("target_log_file", dataset)
            playback_speed = mode_cfg.get("playback_speed", playback_speed)
            loop_value = mode_cfg.get("loop", loop_value)
            replay_action = mode_cfg.get("replay_action", replay_action)
            seek_sec = mode_cfg.get("seek_sec", seek_sec)

        mode = str(mode or mode_state["state"]).upper()
        dataset = dataset or mode_state["dataset"]
        playback_speed = float(playback_speed if playback_speed is not None else mode_state["playback_speed"])
        loop_value = bool(mode_state["loop"] if loop_value is None else loop_value)
        replay_action = str(replay_action or "").upper()
        seek_sec = float(seek_sec) if seek_sec is not None else None
        return mode, dataset, playback_speed, loop_value, replay_action, seek_sec

    def handle_system_mode(message, now):
        nonlocal replay_injector
        mode, dataset, playback_speed, loop_value, replay_action, seek_sec = _normalize_mode_message(message)

        success = True
        status_message = "OK"

        if mode == "REPLAY":
            replay_candidate = ReplayInjector(
                file_path=dataset,
                playback_speed=playback_speed,
                loop=loop_value,
            )
            if not replay_candidate.is_ready():
                success = False
                status_message = f"Replay file unavailable or empty: {dataset}"
            else:
                serial_mgr.stop()
                packet_queue.get_all()
                replay_candidate.reset(now)
                replay_injector = replay_candidate
                reset_tracking_state()
                mode_state.update({
                    "state": "REPLAY",
                    "dataset": dataset,
                    "playback_speed": replay_candidate.playback_speed,
                    "loop": loop_value,
                    "paused": False,
                    "position_sec": 0.0,
                    "duration_sec": round(replay_candidate.duration_seconds(), 3),
                })
                telemetry.set_replay_mode(True)
        elif mode == "LIVE":
            replay_injector = None
            packet_queue.get_all()
            reset_tracking_state()
            mode_state.update({
                "state": "LIVE",
                "dataset": dataset,
                "playback_speed": playback_speed,
                "loop": loop_value,
                "paused": False,
                "position_sec": 0.0,
                "duration_sec": 0.0,
            })
            telemetry.set_replay_mode(False)
            serial_mgr.start()
        else:
            success = False
            status_message = f"Unsupported mode: {mode}"

        if success and mode_state["state"] == "REPLAY" and replay_injector:
            if replay_action == "PAUSE":
                mode_state["paused"] = True
            elif replay_action == "RESUME":
                mode_state["paused"] = False
                replay_injector.start_wall_time = now - (replay_injector.progress_seconds() / max(0.05, mode_state["playback_speed"]))
            elif replay_action == "STOP":
                mode_state["paused"] = True
                replay_injector.reset(now)
                reset_tracking_state()
            elif replay_action == "SEEK" and seek_sec is not None:
                replay_injector.seek_seconds(seek_sec, now)
                reset_tracking_state()
                mode_state["position_sec"] = round(replay_injector.progress_seconds(), 3)
            elif replay_action and replay_action not in {"PAUSE", "RESUME", "STOP", "SEEK"}:
                success = False
                status_message = f"Unsupported replay_action: {replay_action}"

        _broadcast("system_mode_ack", {
            "success": success,
            "message": status_message,
            "mode": mode_state,
            "datasets": list_available_datasets("."),
        }, now)

    def handle_config_update(message, now):
        config_update = message.get("config", {})
        save_flag = bool(message.get("save", False))
        applied = {}

        if isinstance(config_update, dict):
            pipeline_cfg = config.setdefault("pipeline", {})
            if "heartbeat_timeout" in config_update:
                pipeline_cfg["heartbeat_timeout"] = int(config_update["heartbeat_timeout"])
                applied["heartbeat_timeout"] = pipeline_cfg["heartbeat_timeout"]
            if "processing_window_ms" in config_update:
                window_ms = int(config_update["processing_window_ms"])
                pipeline_cfg["time_window"] = max(0.05, window_ms / 1000.0)
                applied["processing_window_ms"] = window_ms

        if save_flag:
            save_config(config, config_path)

        _broadcast("config_ack", {
            "success": True,
            "saved": save_flag,
            "applied": applied,
        }, now)

    def handle_recording_control(message, now):
        nonlocal recorder_file
        action = str(message.get("action", "")).upper()
        success = True
        status_message = "OK"

        if action == "START":
            requested_name = (message.get("filename") or "walk_test").strip()
            safe_name = requested_name.replace(" ", "_")
            if not safe_name.endswith(".jsonl"):
                safe_name = f"{safe_name}.jsonl"
            if recorder_file and not recorder_file.closed:
                recorder_file.close()
            recorder_file = open(safe_name, "a")
            recording_state["enabled"] = True
            recording_state["filename"] = safe_name
            ensure_recording_header(recorder_file, recording_state["filename"])
        elif action == "STOP":
            recording_state["enabled"] = False
            if recorder_file and not recorder_file.closed:
                recorder_file.close()
            recorder_file = open(recording_state["filename"], "a")
            ensure_recording_header(recorder_file, recording_state["filename"])
        else:
            success = False
            status_message = f"Unsupported recording action: {action}"

        _broadcast("recording_ack", {
            "success": success,
            "message": status_message,
            "recording": recording_state,
        }, now)

    def handle_debug_command(message, now):
        action = str(message.get("action", "")).upper()
        if action == "SHOW_TRIANGLES":
            debug_state["show_triangles"] = True
        elif action == "HIDE_TRIANGLES":
            debug_state["show_triangles"] = False
        elif action == "SHOW_NODE_SPHERES":
            debug_state["show_node_spheres"] = True
        elif action == "HIDE_NODE_SPHERES":
            debug_state["show_node_spheres"] = False

        _broadcast("debug_ack", {
            "success": True,
            "debug": debug_state,
        }, now)

    def handle_ping(_message, now):
        _broadcast("PONG", {
            "uptime": round(now - start_time, 2),
            "version": "1.0.0",
            "mode": mode_state,
        }, now)

    command_handlers = {
        "SYSTEM_MODE": handle_system_mode,
        "CALIBRATION_UPDATE": handle_calibration,
        "CONFIG_UPDATE": handle_config_update,
        "RECORDING_CONTROL": handle_recording_control,
        "DEBUG_COMMAND": handle_debug_command,
        "PING": handle_ping,
    }

    try:
        ws_server.start()
        serial_mgr.start()
        
        last_snapshot_time = 0
        node_rate_sample_time = time.time()
        previous_node_counts = {}
        node_packet_hz = {node: 0.0 for node in VISUAL_NODE_POSITIONS}
        last_packet_ingest_at = time.time()
        
        while True:
            loop_start = time.time()
            now = time.time()

            while True:
                try:
                    inbound = control_messages.get_nowait()
                except queue.Empty:
                    break

                message_type = str(inbound.get("type", "")).upper()
                handler = command_handlers.get(message_type)
                if not handler:
                    logger.warning("Ignoring unsupported websocket message type: %s", message_type)
                    continue
                handler(inbound, now)
            
            # 1. Ingest packets
            if mode_state["state"] == "REPLAY":
                if replay_injector:
                    mode_state["duration_sec"] = round(replay_injector.duration_seconds(), 3)
                    mode_state["position_sec"] = round(replay_injector.progress_seconds(), 3)
                if replay_injector and not mode_state.get("paused", False):
                    packets = replay_injector.next_packets(now)
                else:
                    packets = []
            else:
                packets = packet_queue.get_all()

            if packets:
                last_packet_ingest_at = now
                for p in packets:
                    # Write to recorder and extract heartbeat metrics
                    if recording_state["enabled"] and mode_state["state"] == "LIVE":
                        recorder_file.write(json.dumps(p) + "\n")
                    if "status" in p or "heartbeat" in p:
                        heartbeat.update(p["node"])
                    
                    telemetry.update_node(
                        name=p.get("node", "unknown"),
                        connected=True,
                        packet_count=telemetry.state["nodes"].get(p.get("node"), {}).get("packet_count", 0) + 1,
                        last_packet_time=p.get("jetson_timestamp", now)
                    )
                    telemetry.increment_processed()
                
                # 2. Time Alignment
                aligner.add_packets(packets)
            
            # Use current Jetson time to evaluate the window buffer
            window_packets = aligner.get_aligned_windows(now)
            zone_metrics = ambient_analyzer.analyze_ambient_zones(window_packets)
            telemetry.update_ambient_zones(zone_metrics)
            
            if window_packets:
                # 3. Feature Extraction
                spatial_vec, metadata = extractor.extract(window_packets)
                
                # 4. Spatial Estimation
                clusters = spatial_tracker.estimate_clusters([spatial_vec], [metadata])
                
                # 5. Identity Tracking
                identities = identity_tracker.resolve_identity(clusters)
                
                # 6. Publish live visualization target from the current telemetry window.
                tracking_target = estimate_tracking(window_packets, calibrator, node_packet_hz, runtime_controls, mode_state)
                if tracking_target:
                    _broadcast("tracking_update", {
                        "targets": [tracking_target],
                        "identities": identities,
                        "system_mode": mode_state,
                        "debug": debug_state,
                    }, now)

            heartbeat.check_health()
            recorder_file.flush()
            
            # Update telemetry metrics
            loop_duration = time.time() - loop_start
            telemetry.update_pipeline(
                queue_depth=packet_queue.queue.qsize(),
                dropped=packet_queue.dropped_packets,
                latency=loop_duration,
                clients_count=ws_server.client_count()
            )
            
            # Broadcast snapshot at 2Hz
            if now - last_snapshot_time > 0.5:
                sample_seconds = now - node_rate_sample_time
                node_packet_hz = _compute_node_packet_rates(
                    telemetry.state.get("nodes", {}),
                    previous_node_counts,
                    sample_seconds,
                )
                node_rate_sample_time = now

                avg_rate = sum(node_packet_hz.values()) / max(1, len(node_packet_hz))
                queue_depth = packet_queue.queue.qsize()
                serial_staleness = now - last_packet_ingest_at

                serial_health = "green"
                if serial_staleness > 2.0:
                    serial_health = "red"
                elif avg_rate < 15.0:
                    serial_health = "yellow"

                queue_health = "green"
                if packet_queue.dropped_packets > 0 or queue_depth >= 5000:
                    queue_health = "red"
                elif queue_depth > 50:
                    queue_health = "yellow"

                processing_health = "green"
                if loop_duration > 0.12:
                    processing_health = "red"
                elif loop_duration > 0.06:
                    processing_health = "yellow"

                telemetry.state["pipeline"]["health"] = {
                    "serial": serial_health,
                    "queue": queue_health,
                    "calibration": processing_health,
                    "fusion": processing_health,
                    "tracker": processing_health,
                    "websocket": "green" if ws_server.client_count() > 0 else "yellow",
                    "metrics": {
                        "avg_packet_hz": round(avg_rate, 2),
                        "serial_staleness_sec": round(serial_staleness, 2),
                        "queue_depth": queue_depth,
                        "loop_latency_ms": round(loop_duration * 1000, 2),
                    },
                }

                snapshot = telemetry.get_snapshot()
                snapshot["schema"] = SCHEMA_VERSION
                ws_server.broadcast(snapshot)
                last_snapshot_time = now
                
            time.sleep(0.01)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        serial_mgr.stop()
        recorder_file.close()

if __name__ == "__main__":
    main()