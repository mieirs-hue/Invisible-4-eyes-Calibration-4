class AmbientZoneAnalyzer:
    def __init__(self, calibrator, node_zone_map, zone_multipliers=None, density_reference=80):
        self.calibrator = calibrator
        self.node_zone_map = node_zone_map
        self.zone_multipliers = zone_multipliers or {}
        self.density_reference = max(1, int(density_reference))

    def analyze_ambient_zones(self, window_packets):
        zone_accumulators = {}

        for node, zone in self.node_zone_map.items():
            zone_accumulators[zone] = {
                "packet_count": 0,
                "strength_sum": 0.0,
                "source_node": node
            }

        for packet in window_packets:
            if "status" in packet or "heartbeat" in packet:
                continue

            node_name = packet.get("node")
            if node_name not in self.node_zone_map:
                continue

            zone_name = self.node_zone_map[node_name]
            normalized_rssi = self.calibrator.calibrate(packet.get("rssi", -100), node_name)

            zone_accumulators[zone_name]["packet_count"] += 1
            zone_accumulators[zone_name]["strength_sum"] += normalized_rssi

        zone_metrics = {}
        for zone_name, stats in zone_accumulators.items():
            packet_count = stats["packet_count"]
            average_strength = (stats["strength_sum"] / packet_count) if packet_count else 0.0
            density_score = min(packet_count / self.density_reference, 1.0)
            multiplier = float(self.zone_multipliers.get(zone_name, 1.0))

            # Blend signal strength with packet density for robust ambient pressure.
            rf_pressure = ((average_strength * 0.75) + (density_score * 0.25)) * multiplier
            rf_pressure = max(0.0, min(rf_pressure, 2.0))

            zone_metrics[zone_name] = {
                "rf_pressure": round(rf_pressure, 4),
                "avg_strength": round(average_strength, 4),
                "packet_count": packet_count,
                "multiplier": round(multiplier, 3),
                "source_node": stats["source_node"]
            }

        return zone_metrics