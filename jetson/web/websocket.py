import asyncio
import websockets
import json
import threading
import logging

logger = logging.getLogger(__name__)

class WebSocketServer:
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve_forever())
        self.loop.run_forever()

    async def _serve_forever(self):
        async with websockets.serve(self._handler, self.host, self.port):
            logger.info(f"WebSocket Server started on ws://{self.host}:{self.port}")
            await asyncio.Future()

    async def _handler(self, websocket, *args):
        self.clients.add(websocket)
        logger.info(f"Client connected. Total clients: {len(self.clients)}")
        try:
            async for _ in websocket:
                pass # We only broadcast, no need to handle incoming messages yet
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.remove(websocket)
            logger.info(f"Client disconnected. Total clients: {len(self.clients)}")

    def start(self):
        self.thread.start()

    def broadcast(self, message):
        """Thread-safe broadcast"""
        if not self.clients:
            return
            
        async def _broadcast():
            payload = json.dumps(message)
            if self.clients:
                await asyncio.gather(*[client.send(payload) for client in self.clients])

        asyncio.run_coroutine_threadsafe(_broadcast(), self.loop)

    def client_count(self):
        return len(self.clients)