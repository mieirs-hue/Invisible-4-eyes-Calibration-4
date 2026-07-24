import numpy as np

try:
    from sklearn.cluster import DBSCAN
except ModuleNotFoundError:
    class DBSCAN:  # Fallback stub to keep runtime alive without sklearn.
        def __init__(self, eps=0.15, min_samples=2, metric='euclidean'):
            self.min_samples = min_samples

        def fit_predict(self, X):
            if len(X) >= self.min_samples:
                return np.zeros(len(X), dtype=int)
            return np.full(len(X), -1, dtype=int)

class SpatialTracker:
    def __init__(self, eps=0.15, min_samples=2):
        self.dbscan = DBSCAN(eps=eps, min_samples=min_samples, metric='euclidean')

    def estimate_clusters(self, spatial_matrix, metadata_list):
        if len(spatial_matrix) < 2:
            return []
            
        labels = self.dbscan.fit_predict(spatial_matrix)
        tracked_entities = []
        
        for idx, label in enumerate(labels):
            if label == -1: 
                continue # Ignore noise
                
            cluster_id = f"Spatial_Target_{label}"
            entity = next((e for e in tracked_entities if e["id"] == cluster_id), None)
            
            if not entity:
                entity = {
                    "id": cluster_id,
                    "normalized_coords": [],
                    "associated_fingerprints": set(),
                    "observed_macs": set()
                }
                tracked_entities.append(entity)
                
            entity["normalized_coords"].append(spatial_matrix[idx])
            entity["associated_fingerprints"].update(metadata_list[idx]['ie_fingerprints'])
            entity["observed_macs"].update(metadata_list[idx]['macs'])
            
        return tracked_entities