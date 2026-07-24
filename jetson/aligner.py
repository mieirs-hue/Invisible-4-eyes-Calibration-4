class TemporalAligner:
    def __init__(self, time_window=0.5):
        self.time_window = time_window
        self.buffer = []

    def add_packets(self, packets):
        self.buffer.extend(packets)

    def get_aligned_windows(self, now):
        # Keep packets that are within the current time window
        valid_buffer = [
            p for p in self.buffer
            if now - p["jetson_timestamp"] <= self.time_window
        ]
        
        # Shift the oldest out dynamically
        self.buffer = valid_buffer
        return self.buffer