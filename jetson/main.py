import time
import json
from config import load_config
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


VISUAL_NODE_POSITIONS = {
    "north": (10.0, -5.0),
    "south": (-10.0, 5.0),
    "east": (-10.0, -5.0),
    "west": (10.0, 5.0),
}


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def estimate_tracking(window_packets, calibrator):
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

    return {
        "id": "human_target",
        "position": [round(target_x, 3), 3.0, round(target_z, 3)],
        "confidence": round(confidence, 3),
        "radii": radii,
        "confirmed_nodes": top_three,
        "node_strengths": {node: round(strength, 4) for node, strength in node_strengths.items()},
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
    ws_server = WebSocketServer(port=config["pipeline"].get("websocket_port", 8765))
    
    # Optional Data Recorder for replay
    recorder_file = open("recorded_packets.jsonl", "a")

    try:
        ws_server.start()
        serial_mgr.start()
        
        last_snapshot_time = 0
        
        while True:
            loop_start = time.time()
            now = time.time()
            
            # 1. Ingest packets
            packets = packet_queue.get_all()
            if packets:
                for p in packets:
                    # Write to recorder and extract heartbeat metrics
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
                tracking_target = estimate_tracking(window_packets, calibrator)
                if tracking_target:
                    ws_server.broadcast({
                        "protocol": "invisible4eyes.telemetry",
                        "version": "1.0.0",
                        "type": "tracking_update",
                        "observation_time": now,
                        "publish_time": time.time(),
                        "payload": {
                            "targets": [tracking_target],
                            "identities": identities,
                        },
                    })

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
                ws_server.broadcast(telemetry.get_snapshot())
                last_snapshot_time = now
                
            time.sleep(0.01)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        serial_mgr.stop()
        recorder_file.close()

if __name__ == "__main__":
    main()