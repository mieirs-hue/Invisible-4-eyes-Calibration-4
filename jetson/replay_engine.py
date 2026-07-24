import time
import json
import logging

def replay_dataset(jsonl_path, packet_queue, running_flag, mode="real-time"):
    """Reads historical datasets. Mode can be set to 'real-time' or 'accelerated'."""
    logging.info(f"Initializing dataset playback engine in [{mode.upper()}] mode.")
    
    try:
        with open(jsonl_path, 'r') as f:
            first_line = f.readline()
            if not first_line:
                return
            first_packet = json.loads(first_line)
            f.seek(0)
            
            log_start_time = first_packet.get("publish_time") or first_packet.get("timestamp")
            playback_start_time = time.time()
            
            for line in f:
                if not running_flag():
                    break
                    
                packet = json.loads(line)
                
                if mode == "real-time":
                    packet_time = packet.get("publish_time") or packet.get("timestamp")
                    target_delay = packet_time - log_start_time
                    elapsed = time.time() - playback_start_time
                    sleep_duration = target_delay - elapsed
                    if sleep_duration > 0:
                        time.sleep(sleep_duration)
                
                # Maintain timeline continuity for the state estimator
                packet["observation_time"] = time.time()
                packet_queue.put(packet)
                
        logging.info("Dataset playback routine completed successfully.")
    except Exception as e:
        logging.error(f"Playback runtime failure: {e}")