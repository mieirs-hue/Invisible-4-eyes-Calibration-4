class Calibration:
    def __init__(self, config):
        self.nodes = config.get("nodes", {})

    def calibrate(self, raw_rssi, node_name):
        # Apply hardware offset and gain
        node_conf = self.nodes.get(node_name, {})
        offset = node_conf.get("offset", 0.0)
        gain = node_conf.get("gain", 1.0)
        
        corrected = (raw_rssi * gain) + offset
        
        # Limit between -100dBm (floor) and -30dBm (ceiling)
        clipped = max(min(corrected, -30.0), -100.0)
        
        # Linear scaling to [0.0, 1.0] domain
        return (clipped + 100.0) / 70.0