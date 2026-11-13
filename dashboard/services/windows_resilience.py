#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Windows Asyncio IOCP Proactor Resilience Service.

Patches CPython's asyncio ProactorEventLoop on Windows to gracefully handle
transient client disconnect errors (WinError 64 ERROR_NETNAME_DELETED,
WinError 121 ERROR_SEM_TIMEOUT, WinError 1236 ERROR_CONNECTION_ABORTED,
and WSAECONNRESET 10054) during overlapped AcceptEx operations.

Prevents premature server listening socket closure and unhandled task exceptions
when clients abort TCP connections during browser page reloads or proxy health checks.
"""

import sys
import logging

logger = logging.getLogger("intelligent_tracker.windows_resilience")

# Transient Windows socket error codes when client drops connection during AcceptEx
TRANSIENT_WIN_SOCKET_ERRORS = {
    64,     # ERROR_NETNAME_DELETED: "The specified network name is no longer available"
    121,    # ERROR_SEM_TIMEOUT: "The semaphore timeout period has expired"
    1236,   # ERROR_CONNECTION_ABORTED: "The network connection was aborted by the local system"
    10054,  # WSAECONNRESET: "An existing connection was forcibly closed by the remote host"
}

_PATCHED = False


def apply_windows_iocp_patch() -> bool:
    """
    Safely patch asyncio Proactor event loop on Windows to prevent listening socket
    closure and unhandled task exceptions on transient AcceptEx client disconnects.
    """
    global _PATCHED
    if _PATCHED or sys.platform != "win32":
        return False

    try:
        import asyncio.proactor_events as pe
        import asyncio.windows_events as we

        orig_start_serving = pe.BaseProactorEventLoop._start_serving

        def patched_start_serving(
            self,
            protocol_factory,
            sock,
            sslcontext=None,
            server=None,
            backlog=100,
            ssl_handshake_timeout=None,
            ssl_shutdown_timeout=None,
        ):
            def loop(f=None):
                try:
                    if f is not None:
                        try:
                            conn, addr = f.result()
                        except OSError as exc:
                            winerr = getattr(exc, "winerror", None)
                            if winerr in TRANSIENT_WIN_SOCKET_ERRORS:
                                logger.debug(
                                    "Absorbed transient Windows socket accept error (WinError %s)",
                                    winerr,
                                )
                                if not self.is_closed() and sock.fileno() != -1:
                                    f_next = self._proactor.accept(sock)
                                    self._accept_futures[sock.fileno()] = f_next
                                    f_next.add_done_callback(loop)
                                return
                            raise

                        if self._debug:
                            pe.logger.debug("%r got a new connection from %r: %r", server, addr, conn)
                        protocol = protocol_factory()
                        if sslcontext is not None:
                            self._make_ssl_transport(
                                conn,
                                protocol,
                                sslcontext,
                                server_side=True,
                                extra={"peername": addr},
                                server=server,
                                ssl_handshake_timeout=ssl_handshake_timeout,
                                ssl_shutdown_timeout=ssl_shutdown_timeout,
                            )
                        else:
                            self._make_socket_transport(
                                conn, protocol, extra={"peername": addr}, server=server
                            )

                    if self.is_closed():
                        return
                    f = self._proactor.accept(sock)
                except OSError as exc:
                    if sock.fileno() != -1:
                        self.call_exception_handler({
                            "message": "Accept failed on a socket",
                            "exception": exc,
                            "socket": pe.trsock.TransportSocket(sock),
                        })
                        sock.close()
                    elif self._debug:
                        pe.logger.debug("Accept failed on socket %r", sock, exc_info=True)
                except pe.exceptions.CancelledError:
                    sock.close()
                else:
                    self._accept_futures[sock.fileno()] = f
                    f.add_done_callback(loop)

            self.call_soon(loop)

        pe.BaseProactorEventLoop._start_serving = patched_start_serving

        orig_accept = we.IocpProactor.accept

        def patched_accept(self, listener):
            self._register_with_iocp(listener)
            conn = self._get_accept_socket(listener.family)
            ov = we._overlapped.Overlapped(we.NULL)
            ov.AcceptEx(listener.fileno(), conn.fileno())

            def finish_accept(trans, key, ov):
                ov.getresult()
                buf = we.struct.pack("@P", listener.fileno())
                conn.setsockopt(
                    we.socket.SOL_SOCKET,
                    we._overlapped.SO_UPDATE_ACCEPT_CONTEXT,
                    buf,
                )
                conn.settimeout(listener.gettimeout())
                return conn, conn.getpeername()

            async def accept_coro(future, conn):
                try:
                    await future
                except we.exceptions.CancelledError:
                    conn.close()
                    raise
                except OSError as exc:
                    conn.close()
                    if getattr(exc, "winerror", None) not in TRANSIENT_WIN_SOCKET_ERRORS:
                        raise

            future = self._register(ov, listener, finish_accept)
            coro = accept_coro(future, conn)
            we.tasks.ensure_future(coro, loop=self._loop)
            return future

        we.IocpProactor.accept = patched_accept

        _PATCHED = True
        logger.info("Applied Windows IOCP Proactor transient socket resilience patch.")
        return True
    except Exception as e:
        logger.warning("Failed to apply Windows IOCP resilience patch: %s", e)
        return False


def apply_windows_process_containment() -> bool:
    """
    Assign the current process and its child hierarchy to a Win32 Job Object
    configured with KILL_ON_JOB_CLOSE to guarantee atomic process tree containment.
    """
    from dashboard.services.process_supervisor import assign_to_job_object
    return assign_to_job_object()


