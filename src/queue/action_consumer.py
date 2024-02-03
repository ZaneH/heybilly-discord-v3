import json
import logging
import aio_pika

logger = logging.getLogger(__name__)


class ActionConsumer:
    def __init__(self, connection, loop, queue_name, action_queue, host="localhost"):
        self.connection = connection
        self.loop = loop
        self.queue_name = queue_name
        self.action_queue = action_queue
        self.host = host

    async def on_message(self, message: aio_pika.IncomingMessage):
        async with message.process():
            action = json.loads(message.body)
            await self.action_queue.put(action)

    async def start_consuming(self):
        if not self.connection:
            logger.error("No connection to RabbitMQ.")
            return

        channel = await self.connection.channel()
        queue = await channel.get_queue(self.queue_name)

        await queue.consume(self.on_message)

    async def close_connection(self):
        if self.connection:
            await self.connection.close()
