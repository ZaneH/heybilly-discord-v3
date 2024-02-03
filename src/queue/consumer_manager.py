import logging
import aio_pika

from src.queue.action_consumer import ActionConsumer
logger = logging.getLogger(__name__)


class ConsumerManager:
    def __init__(self, loop, host="localhost"):
        self.loop = loop
        self.host = host
        self.connection = None
        self.consumers = []

    async def start(self):
        self.connection = await aio_pika.connect_robust(host=self.host, loop=self.loop)
        if self.connection:
            logger.info("Connected to RabbitMQ.")
        else:
            logger.error("Failed to connect to RabbitMQ.")

    async def create_consumer(self, queue_name, action_queue):
        consumer = ActionConsumer(
            self.connection, self.loop, queue_name, action_queue)
        self.consumers.append(consumer)
        await consumer.start_consuming()

    async def close(self):
        if self.connection:
            await self.connection.close()
