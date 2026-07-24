class IdentityTracker:
    def __init__(self):
        self.known_identities = {}
        self.next_id = 1

    def resolve_identity(self, tracked_entities):
        assigned_entities = []
        for entity in tracked_entities:
            matched_id = None
            # Trivial MAC matching capability
            for mac in entity["observed_macs"]:
                if mac in self.known_identities:
                    matched_id = self.known_identities[mac]
                    break
            
            if matched_id is None:
                matched_id = self.next_id
                self.next_id += 1
                for mac in entity["observed_macs"]:
                    self.known_identities[mac] = matched_id
                    
            assigned_entities.append({
                "assigned_id": matched_id,
                "spatial_data": entity
            })
        return assigned_entities