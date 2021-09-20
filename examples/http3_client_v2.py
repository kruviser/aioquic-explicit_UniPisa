import argparse
import asyncio
import logging
import os
import pickle
import sys
import ssl
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Union, cast
from urllib.parse import urlparse

import wsproto
import wsproto.events
from quic_logger import QuicDirectoryLogger

import aioquic
from aioquic.asyncio.client import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h0.connection import H0_ALPN, H0Connection
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import (
    DataReceived,
    H3Event,
    HeadersReceived,
    PushPromiseReceived,
)
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent
from aioquic.tls import CipherSuite, SessionTicket

try:
    import uvloop
except ImportError:
    uvloop = None

logger = logging.getLogger("client")

HttpConnection = Union[H0Connection, H3Connection]

USER_AGENT = "aioquic/" + aioquic.__version__


class URL:
    def __init__(self, url: str) -> None:
        parsed = urlparse(url)

        self.authority = parsed.netloc
        self.full_path = parsed.path
        if parsed.query:
            self.full_path += "?" + parsed.query
        self.scheme = parsed.scheme


class HttpRequest:
    def __init__(
        self, method: str, url: URL, content: bytes = b"", headers: Dict = {}
    ) -> None:
        self.content = content
        self.headers = headers
        self.method = method
        self.url = url


class WebSocket:
    def __init__(
        self, http: HttpConnection, stream_id: int, transmit: Callable[[], None]
    ) -> None:
        self.http = http
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.stream_id = stream_id
        self.subprotocol: Optional[str] = None
        self.transmit = transmit
        self.websocket = wsproto.Connection(wsproto.ConnectionType.CLIENT)

    async def close(self, code=1000, reason="") -> None:
        """
        Perform the closing handshake.
        """
        data = self.websocket.send(
            wsproto.events.CloseConnection(code=code, reason=reason)
        )
        self.http.send_data(stream_id=self.stream_id, data=data, end_stream=True)
        self.transmit()

    async def recv(self) -> str:
        """
        Receive the next message.
        """
        return await self.queue.get()

    async def send(self, message: str) -> None:
        """
        Send a message.
        """
        assert isinstance(message, str)

        data = self.websocket.send(wsproto.events.TextMessage(data=message))
        self.http.send_data(stream_id=self.stream_id, data=data, end_stream=False)
        self.transmit()

    def http_event_received(self, event: H3Event) -> None:
        if isinstance(event, HeadersReceived):
            for header, value in event.headers:
                if header == b"sec-websocket-protocol":
                    self.subprotocol = value.decode()
        elif isinstance(event, DataReceived):
            self.websocket.receive_data(event.data)

        for ws_event in self.websocket.events():
            self.websocket_event_received(ws_event)

    def websocket_event_received(self, event: wsproto.events.Event) -> None:
        if isinstance(event, wsproto.events.TextMessage):
            self.queue.put_nowait(event.data)


class HttpClient(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.pushes: Dict[int, Deque[H3Event]] = {}
        self._http: Optional[HttpConnection] = None
        self._request_events: Dict[int, Deque[H3Event]] = {}
        self._request_waiter: Dict[int, asyncio.Future[Deque[H3Event]]] = {}
        self._websockets: Dict[int, WebSocket] = {}

        if self._quic.configuration.alpn_protocols[0].startswith("hq-"):
            self._http = H0Connection(self._quic)
        else:
            self._http = H3Connection(self._quic)

    async def get(self, url: str, counter:int, n_request_migration:int, interval_migration:int,  headers: Dict = {} ) -> Deque[H3Event]:   #DEBUG2 TEST* DEBUG V2* #PERF EV AUTOMATION* DEBUG V3*
        """ 
        Perform a GET request.
        """
        return await self._request(
            HttpRequest(method="GET", url=URL(url), headers=headers), counter, n_request_migration, interval_migration   #DEBUG2 TEST* DEBUG V2* #PERF EV AUTOMATION* DEBUG V3*
        )

    async def post(self, url: str, data: bytes, counter:int, n_request_migration:int, interval_migration:int,  headers: Dict = {} ) -> Deque[H3Event]:   #DEBUG2 TEST* DEBUG V2* #PERF EV AUTOMATION* DEBUG V3*
        """
        Perform a POST request.
        """
        return await self._request(
            HttpRequest(method="POST", url=URL(url), content=data, headers=headers), counter, n_request_migration, interval_migration   #DEBUG2 TEST* DEBUG V2* #PERF EV AUTOMATION* DEBUG V3*
        )

    async def websocket(self, url: str, subprotocols: List[str] = []) -> WebSocket:
        """
        Open a WebSocket.
        """
        request = HttpRequest(method="CONNECT", url=URL(url))
        stream_id = self._quic.get_next_available_stream_id()
        websocket = WebSocket(
            http=self._http, stream_id=stream_id, transmit=self.transmit
        )

        self._websockets[stream_id] = websocket

        headers = [
            (b":method", b"CONNECT"),
            (b":scheme", b"https"),
            (b":authority", request.url.authority.encode()),
            (b":path", request.url.full_path.encode()),
            (b":protocol", b"websocket"),
            (b"user-agent", USER_AGENT.encode()),
            (b"sec-websocket-version", b"13"),
        ]
        if subprotocols:
            headers.append(
                (b"sec-websocket-protocol", ", ".join(subprotocols).encode())
            )
        self._http.send_headers(stream_id=stream_id, headers=headers)

        self.transmit()

        return websocket

    def http_event_received(self, event: H3Event) -> None:
        if isinstance(event, (HeadersReceived, DataReceived)):
            stream_id = event.stream_id
            if stream_id in self._request_events:
                # http
                self._request_events[event.stream_id].append(event)
                if event.stream_ended:
                    request_waiter = self._request_waiter.pop(stream_id)
                    request_waiter.set_result(self._request_events.pop(stream_id))

            elif stream_id in self._websockets:
                # websocket
                websocket = self._websockets[stream_id]
                websocket.http_event_received(event)

            elif event.push_id in self.pushes:
                # push
                self.pushes[event.push_id].append(event)

        elif isinstance(event, PushPromiseReceived):
            self.pushes[event.push_id] = deque()
            self.pushes[event.push_id].append(event)

    def quic_event_received(self, event: QuicEvent) -> None:
        #  pass event to the HTTP layer
        if self._http is not None:
            for http_event in self._http.handle_event(event):
                self.http_event_received(http_event)

    async def _request(self, request: HttpRequest, counter:int, n_request_migration:int, interval_migration:int ):    #DEBUG2 TEST* DEBUG V2* PERF EV AUTOMATION* DEBUG V3* 
        stream_id = self._quic.get_next_available_stream_id()
        self._http.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", request.method.encode()),
                (b":scheme", request.url.scheme.encode()),
                (b":authority", request.url.authority.encode()),
                (b":path", request.url.full_path.encode()),
                (b"user-agent", USER_AGENT.encode()),
            ]
            + [(k.encode(), v.encode()) for (k, v) in request.headers.items()],
        )
        self._http.send_data(stream_id=stream_id, data=request.content, end_stream=True)

        waiter = self._loop.create_future()
        self._request_events[stream_id] = deque()
        self._request_waiter[stream_id] = waiter

        self.transmit(counter = counter, n_request_migration = n_request_migration, interval_migration = interval_migration)    #DEBUG2 TEST* DEBUG V2* PERF EV AUTOMATION* DEBUG V3*

        return await asyncio.shield(waiter)


async def perform_http_request(
    client: HttpClient, url: str, data: str, include: bool, output_dir: Optional[str], counter: int, n_request_migration: int, interval_migration: int #DEBUG2 TEST* DEBUG V2* PERF EV AUTOMATION* DEBUG V3*       
) -> None: 
    # perform request
    start = time.time()
    if data is not None:
        http_events = await client.post(
            url,
            data=data.encode(),
            counter=counter,
            n_request_migration=n_request_migration,
            interval_migration=interval_migration,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    else:
        http_events = await client.get(url, counter, n_request_migration, interval_migration)   #DEBUG2 TEST* DEBUG V2* PERF EV AUTOMATION* DEBUG V3*
    elapsed = time.time() - start

    # print speed
    octets = 0
    for http_event in http_events:
        if isinstance(http_event, DataReceived):
            octets += len(http_event.data)
    logger.info(
        "Received %d bytes in %.1f s (%.3f Mbps)"
        % (octets, elapsed, octets * 8 / elapsed / 1000000)
    )

    # output response
    if output_dir is not None:
        output_path = os.path.join(
            output_dir, os.path.basename(urlparse(url).path) or "index.html"
        )
        with open(output_path, "wb") as output_file:
            for http_event in http_events:
                if isinstance(http_event, HeadersReceived) and include:
                    headers = b""
                    for k, v in http_event.headers:
                        headers += k + b": " + v + b"\r\n"
                    if headers:
                        output_file.write(headers + b"\r\n")
                elif isinstance(http_event, DataReceived):
                    output_file.write(http_event.data)


def save_session_ticket(ticket: SessionTicket) -> None:
    """
    Callback which is invoked by the TLS engine when a new session ticket
    is received.
    """
    logger.info("New session ticket received")
    if args.session_ticket:
        with open(args.session_ticket, "wb") as fp:
            pickle.dump(ticket, fp)


async def run(
    configuration: QuicConfiguration,
    urls: List[str],
    data: str,
    include: bool,
    output_dir: Optional[str],
    local_port: int,
    zero_rtt: bool,
    n_requests:int, #DEBUG V2
    n_request_migration:int, #PERF EV AUTOMATION*
    interval_migration:int, #DEBUG V3*
    request_type:int, #DEBUG V4*
    request_interval:int, #DEBUG V4*
) -> None:
    # parse URL
    parsed = urlparse(urls[0])
    assert parsed.scheme in (
        "https",
        "wss",
    ), "Only https:// or wss:// URLs are supported."
    if ":" in parsed.netloc:
        host, port_str = parsed.netloc.split(":")
        port = int(port_str)
    else:
        host = parsed.netloc
        port = 443

    async with connect(
        host,
        port,
        configuration=configuration,
        create_protocol=HttpClient,
        session_ticket_handler=save_session_ticket,
        local_port=local_port,
        wait_connected=not zero_rtt,
    ) as client:
        client = cast(HttpClient, client)

        if parsed.scheme == "wss":
            ws = await client.websocket(urls[0], subprotocols=["chat", "superchat"])

            # send some messages and receive reply
            for i in range(2):
                message = "Hello {}, WebSocket!".format(i)
                print("> " + message)
                await ws.send(message)

                message = await ws.recv()
                print("< " + message)

            await ws.close()
        else:
            # perform request
            cont = 0        #DEBUG*
            diff_timestamp=0 #DEBUG V4*
            while(cont < n_requests):  #DEBUG*
                
                print("NUMBER REQUEST --> " + str(cont+1))
                
                #DEBUG V4*****
                if request_type == 1 and diff_timestamp!=0: 
                    print("CLIENT IS SLEEPING")
                    await asyncio.sleep(request_interval - diff_timestamp)  #DEBUG*

                initial_timestamp = time.time() 
                #DEBUG V4*****
                coros = [
                    perform_http_request(
                        client=client,
                        url=url,
                        data=data,
                        include=include,
                        output_dir=output_dir,
                        counter = cont, #DEBUG2 TEST*
                        n_request_migration = n_request_migration, #PERF EV AUTOMATION* 
                        interval_migration = interval_migration, #DEBUG V3
                    )
                    for url in urls
                ]
                await asyncio.gather(*coros)
                final_timestamp = time.time() #DEBUG V4*
                diff_timestamp = final_timestamp - initial_timestamp #DEBUG V4*
                cont+=1 #DEBUG*


if __name__ == "__main__":
    defaults = QuicConfiguration(is_client=True)

    parser = argparse.ArgumentParser(description="HTTP/3 client")
    parser.add_argument(
        "url", type=str, nargs="+", help="the URL to query (must be HTTPS)"
    )
    parser.add_argument(
        "--ca-certs", type=str, help="load CA certificates from the specified file"
    )
    parser.add_argument(
        "--cipher-suites",
        type=str,
        help="only advertise the given cipher suites, e.g. `AES_256_GCM_SHA384,CHACHA20_POLY1305_SHA256`",
    )
    parser.add_argument(
        "-d", "--data", type=str, help="send the specified data in a POST request"
    )
    parser.add_argument(
        "-i",
        "--include",
        action="store_true",
        help="include the HTTP response headers in the output",
    )
    parser.add_argument(
        "--max-data",
        type=int,
        help="connection-wide flow control limit (default: %d)" % defaults.max_data,
    )
    parser.add_argument(
        "--max-stream-data",
        type=int,
        help="per-stream flow control limit (default: %d)" % defaults.max_stream_data,
    )
    parser.add_argument(
        "-k",
        "--insecure",
        action="store_true",
        help="do not validate server certificate",
    )
    parser.add_argument("--legacy-http", action="store_true", help="use HTTP/0.9")
    parser.add_argument(
        "--output-dir", type=str, help="write downloaded files to this directory",
    )
    parser.add_argument(
        "-q",
        "--quic-log",
        type=str,
        help="log QUIC events to QLOG files in the specified directory",
    )
    parser.add_argument(
        "-l",
        "--secrets-log",
        type=str,
        help="log secrets to a file, for use with Wireshark",
    )
    parser.add_argument(
        "-s",
        "--session-ticket",
        type=str,
        help="read and write session ticket from the specified file",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="increase logging verbosity"
    )
    parser.add_argument(
        "--local-port", type=int, default=0, help="local port to bind for connections",
    )
    parser.add_argument(
        "--zero-rtt", action="store_true", help="try to send requests using 0-RTT"
    )
    #DEBUG V2****
    parser.add_argument(
        "-n",
        "--n_requests",
        type=int,
        help="number of requests made by Client to Server during the connection",
    )
    #DEBUG V2*****
    #PERF EV AUTOMATION******
    parser.add_argument(
        "--n_request_migration",
        type=int,
        help="At what request from C to S the command to start the migration of the S should be run",
    )
    #PERF EV AUTOMATION******
    #DEBUG V3*****
    parser.add_argument(
        "--interval_migration",
        type=int,
        help="At what frequency the server should migrate in terms of number of requests",
    )
    #DEBUG V3*****
    #DEBUG V4*****
    parser.add_argument(
        "--request_type",
        type=int,
        help="Type of requests from the Client to the Server: 0 --> back to back, 1: interval between each requests, 2: ",
    )
    parser.add_argument(
        "--request_interval",
        type=int,
        help="Timeout between each request used if request type is different from 0",
    )
    #DEBUG V4*****

    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )

    if args.output_dir is not None and not os.path.isdir(args.output_dir):
        raise Exception("%s is not a directory" % args.output_dir)

    # prepare configuration
    configuration = QuicConfiguration(
        is_client=True, alpn_protocols=H0_ALPN if args.legacy_http else H3_ALPN
    )
    if args.ca_certs:
        configuration.load_verify_locations(args.ca_certs)
    if args.cipher_suites:
        configuration.cipher_suites = [
            CipherSuite[s] for s in args.cipher_suites.split(",")
        ]
    if args.insecure:
        configuration.verify_mode = ssl.CERT_NONE
    if args.max_data:
        configuration.max_data = args.max_data
    if args.max_stream_data:
        configuration.max_stream_data = args.max_stream_data
    if args.quic_log:
        configuration.quic_logger = QuicDirectoryLogger(args.quic_log)
    if args.secrets_log:
        configuration.secrets_log_file = open(args.secrets_log, "a")
    if args.session_ticket:
        try:
            with open(args.session_ticket, "rb") as fp:
                configuration.session_ticket = pickle.load(fp)
        except FileNotFoundError:
            pass

    #DEBUG V2*****
    if args.data is not None and args.n_requests is None:
        print("You have to insert the number of requests made by C to S during the connection")
        sys.exit()
    #DEBUG V2*****
    #PERF EV AUTOMATION******
    if args.n_request_migration < 1 or args.n_request_migration >= args.n_requests:
        print("The value of the request when the migration of the S should start has to be greater than 1 (in the request before C receives new S address) and less the number of requests in the whole connection")
        sys.exit()
    #PERF EV AUTOMATION******
    #DEBUG V3******
    if args.interval_migration is None or args.interval_migration < 1 or args.interval_migration >= args.n_requests:
        print("The value of the frequency of the migration of the S should be greater than 1 and less than the number of requests in the whole connection")
        sys.exit()
    #DEBUG V3******
    #DEBUG V4******
    if args.request_type < 0 or args.request_type > 2:
        print("The value of the type of the request has to be between 0 and 2")
        sys.exit()
    if args.request_interval is None:
        args.request_interval = 0
    if args.request_type != 0 and or args.request_interval <= 0:
        print("With this type of request, the interval between request has to be greater than 0")
        sys.exit()
    #DEBUG V4******

    if uvloop is not None:
        uvloop.install()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        run(
            configuration=configuration,
            urls=args.url,
            data=args.data,
            include=args.include,
            output_dir=args.output_dir,
            local_port=args.local_port,
            zero_rtt=args.zero_rtt,
            n_requests = args.n_requests,   #DEBUG V2*
            n_request_migration = args.n_request_migration, #PERF EV AUTOMATION*
            interval_migration = args.interval_migration, #DEBUG V3*
            request_type = args.request_type, #DEBUG V3*
            request_interval = args.request_interval, #DEBUG V3*
        )
    )
