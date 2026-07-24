class FeatureExtractor:
    def __init__(self, calibrator):
        self.calibrator = calibrator

    def extract(self, window_packets):
        vector = {'north': 0.0, 'south': 0.0, 'east': 0.0, 'west': 0.0}
        ie_fingerprints = set()
        observed_macs = set()
        
        for p in window_packets:
            if "status" in p: continue
            
            node = p['node']
            norm_rssi = self.calibrator.calibrate(p.get('rssi', -100), node)
            vector[node] = norm_rssi
            
            if 'ie' in p: ie_fingerprints.add(p['ie'])
            if 'mac' in p: observed_macs.add(p['mac'])
            
        spatial_vector = [vector['north'], vector['south'], vector['east'], vector['west']]
        metadata = {
            'ie_fingerprints': list(ie_fingerprints),
            'macs': list(observed_macs)
        }
        return spatial_vector, metadata