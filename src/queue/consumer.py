import json
import pika


class ActionConsumer:
    def __init__(self, bot, queue_name):
        self.bot = bot
        self.host = "localhost"
        self.queue_name = queue_name
        self.connection = None
        self.channel = None

    def consume(self):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=self.host))
        self.channel = self.connection.channel()
        self.channel.basic_consume(
            self.queue_name, self.callback, auto_ack=True)
        self.channel.start_consuming()

    def stop(self):
        if self.channel:
            self.channel.stop_consuming()

    def callback(self, ch, method, properties, body):
        action_json = json.loads(body)
        self.bot.action_queue.put(action_json)
