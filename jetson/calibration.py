class Calibration:
    def __init__(self, config):
        self.nodes = config.get("nodes", {})
        self.runtime_rf_gain = 1.0
        self.runtime_node_offsets_db = {node: 0.0 for node in self.nodes}

    def update_runtime_gain(self, gain):
        if gain is None:
            return
        self.runtime_rf_gain = max(0.05, float(gain))

    def update_runtime_offsets(self, offsets):
        if not isinstance(offsets, dict):
            return
        for node, value in offsets.items():
            if node not in self.nodes:
                continue
            self.runtime_node_offsets_db[node] = float(value)

    def calibrate(self, raw_rssi, node_name):
        # Apply hardware offset and gain
        node_conf = self.nodes.get(node_name, {})
        offset = node_conf.get("offset", 0.0)
        gain = node_conf.get("gain", 1.0)

        runtime_offset = self.runtime_node_offsets_db.get(node_name, 0.0)
        corrected = (raw_rssi * gain * self.runtime_rf_gain) + offset + runtime_offset
        
        # Limit between -100dBm (floor) and -30dBm (ceiling)
        clipped = max(min(corrected, -30.0), -100.0)
        
        # Linear scaling to [0.0, 1.0] domain
        return (clipped + 100.0) / 70.0