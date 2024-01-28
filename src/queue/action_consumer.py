import json
import aio_pika


class ActionConsumer:
    def __init__(self, loop, queue_name, action_queue, host="localhost"):
        self.loop = loop
        self.queue_name = queue_name
        self.action_queue = action_queue
        self.host = host
        self.connection = None

    async def on_message(self, message: aio_pika.IncomingMessage):
        async with message.process():
            action = json.loads(message.body)
            await self.action_queue.put(action)
        
    async def start_consuming(self):
        self.connection = await aio_pika.connect_robust(host=self.host, loop=self.loop)
        channel = await self.connection.channel()

        queue = await channel.declare_queue(self.queue_name)
        
        await queue.consume(self.on_message)

    async def close_connection(self):
        if self.connection:
            await self.connection.close()

