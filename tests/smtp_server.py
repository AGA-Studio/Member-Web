"""A tiny SMTP server on 127.0.0.1 for the email tests (no mocks).

It speaks just enough SMTP for `smtplib` (EHLO, MAIL, RCPT, DATA, QUIT) and keeps
each received message as bytes. `mode` changes how it behaves:
- "ok": accepts every message.
- "reject": closes the connection right after accepting it (the provider is down).
- "slow": waits `delay` seconds before greeting (the provider is slow).
"""

import socket
import threading
import time


class SmtpServer:
    def __init__(self, mode: str = "ok", delay: float = 0) -> None:
        self.mode = mode
        self.delay = delay
        self.messages: list[bytes] = []
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self.port = self._socket.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> SmtpServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._socket.close()

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            with connection:
                try:
                    self._talk(connection)
                except OSError:
                    pass

    def _talk(self, connection: socket.socket) -> None:
        if self.mode == "reject":
            return
        if self.delay:
            time.sleep(self.delay)
        reader = connection.makefile("rb")
        connection.sendall(b"220 test SMTP\r\n")
        for line in reader:
            command = line.strip().upper()
            if command.startswith((b"EHLO", b"HELO")):
                connection.sendall(b"250 test\r\n")
            elif command.startswith(b"DATA"):
                connection.sendall(b"354 go on\r\n")
                body = b""
                for data_line in reader:
                    if data_line == b".\r\n":
                        break
                    body += data_line
                self.messages.append(body)
                connection.sendall(b"250 queued\r\n")
            elif command.startswith(b"QUIT"):
                connection.sendall(b"221 bye\r\n")
                return
            else:
                connection.sendall(b"250 ok\r\n")
