import json
import pika


class ActionConsumer:
    def __init__(self, host="localhost", queue_name="actions_queue"):
        self.host = host
        self.queue_name = queue_name
        self.channel = None

    def consume(self):
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=self.host))
        self.channel = connection.channel()
        self.channel.basic_consume(
            self.queue_name, self.callback, auto_ack=True)
        self.channel.start_consuming()

    def stop(self):
        if self.channel:
            self.channel.stop_consuming()

    def callback(self, ch, method, properties, body):
        try:
            action_json = json.loads(body)
            print(f"Received action: {action_json}")

            if action_json['node_type'] == 'output.tts':
                print(f"Received TTS output: {action_json['data']['tts_url']}")
        except json.JSONDecodeError as e:
            print("Received invalid JSON.", e)
            print(f"Received message: {body}")
