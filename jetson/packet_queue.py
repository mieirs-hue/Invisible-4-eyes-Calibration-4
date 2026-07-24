import queue

class PacketQueue:
    def __init__(self, maxsize=5000):
        self.queue = queue.Queue(maxsize=maxsize)
        self.dropped_packets = 0

    def put(self, packet):
        try:
            self.queue.put_nowait(packet)
        except queue.Full:
            self.dropped_packets += 1

    def get_all(self):
        packets = []
        while True:
            try:
                packets.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return packets