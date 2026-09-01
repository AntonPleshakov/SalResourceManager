from dataclasses import dataclass
from threading import Thread

from prometheus_client import start_http_server

from tg.observability.definitions import METRICS_LISTEN, METRICS_PORT


@dataclass(frozen=True)
class MetricsServer:
    server: object
    thread: Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def start_metrics_server(
    port: int = METRICS_PORT,
    listen: str = METRICS_LISTEN,
) -> MetricsServer:
    server, thread = start_http_server(port=port, addr=listen)
    return MetricsServer(server, thread)
