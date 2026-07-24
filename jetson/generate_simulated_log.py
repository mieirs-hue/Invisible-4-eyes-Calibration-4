import json
import time
import math
import random

def generate_simulation_dataset(output_path="simulation_run.jsonl", duration=45):
    """
    Generates a mock raw ESP32 telemetry dataset.
    Simulates:
      - Continuous diagnostic node heartbeats.
      - A target entering the ground floor perimeter.
      - The target transitioning to the upper roof security plane.
    """
    nodes = ["north", "south", "east", "west"]
    target_mac = "4a:da:bc:11:22:3f"
    target_ie = "Vendor_IE_Sign_0x99AA"
    
    start_time = time.time()
    total_steps = duration * 10  # 10 Hz sampling intervals
    
    print(f"Generating {duration}s simulation dataset at: {output_path}")
    
    with open(output_path, "w") as f:
        for step in range(total_steps):
            # Calculate a stable time progression offset
            packet_time = start_time + (step * 0.1)
            
            # 1. Emit Node Diagnostics Heartbeats (Every 2 seconds per node)
            if step % 20 == 0:
                for node in nodes:
                    hb_packet = {
                        "status": "NODE_ONLINE",
                        "heartbeat": True,
                        "node": node,
                        "timestamp": packet_time,
                        "firmware_version": "0.9.2",
                        "uptime_seconds": 5000 + int(step * 0.1),
                        "temperature_c": round(41.5 + random.uniform(-0.3, 0.4), 1)
                    }
                    f.write(json.dumps(hb_packet) + "\n")
            
            # 2. Simulate Target Trajectory Path
            # Phase 1 (Steps 0-250): Ground floor orbital movement
            # Phase 2 (Steps 251-450): Roof level approach (Signal strength characteristics shift)
            progress = step / total_steps
            angle = progress * 2 * math.pi * 1.5  # 1.5 rotations around the dome
            
            # Base signal calculations
            base_rssi = -65.0
            noise = random.uniform(-1.5, 1.5)
            
            # Spatial distribution profiles based on position vectors
            node_signals = {
                "north": base_rssi + (math.sin(angle) * 15.0) + noise,
                "south": base_rssi - (math.sin(angle) * 15.0) + noise,
                "east":  base_rssi + (math.cos(angle) * 15.0) + noise,
                "west":  base_rssi - (math.cos(angle) * 15.0) + noise
            }
            
            # If target climbs to the roof level, dramatically compress or spike 
            # specific nodes to simulate changing Z-axis geometry reflections
            if step > 250:
                node_signals["north"] += 8.0  # Simulating overhead clear line-of-sight
                node_signals["south"] += 8.0
            
            # Stream the individual raw node packet arrivals into the log
            for node, rssi in node_signals.items():
                # Randomize arrival times slightly within the 100ms window to simulate USB jitter
                arrival_jitter = random.uniform(0.001, 0.005)
                
                raw_packet = {
                    "timestamp": packet_time + arrival_jitter,
                    "mac": target_mac,
                    "ie": target_ie,
                    "rssi": round(max(min(rssi, -30.0), -95.0), 2),
                    "node": node
                }
                f.write(json.dumps(raw_packet) + "\n")
                
    print("Simulation dataset generation complete. Ready for replay.")

if __name__ == "__main__":
    generate_simulation_dataset()