from __future__ import annotations

import asyncio
import socket
from typing import List

from aiohttp.abc import AbstractResolver, ResolveResult

# Адрес из DNS сейчас часто не отвечает, а этот адрес того же API отвечает.
FALLBACK_API_IPS = ("149.154.167.220",)
API_HOST = "api.telegram.org"


def candidate_ips(dns_ips: List[str]) -> List[str]:
    found: List[str] = []
    for ip in list(FALLBACK_API_IPS) + list(dns_ips):
        if ip and ip not in found:
            found.append(ip)
    return found


def dns_ipv4(host: str) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    ips: List[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    return ips


def _connect_sync(ip: str, port: int, timeout: float) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


async def can_connect(ip: str, port: int = 443, timeout: float = 3) -> bool:
    # Обычный asyncio-коннект к заблокированному адресу не отменяется и висит минуту.
    return await asyncio.get_running_loop().run_in_executor(
        None, _connect_sync, ip, port, timeout
    )


async def first_reachable(ips: List[str], timeout: float = 3) -> str | None:
    if not ips:
        return None
    tasks = {
        asyncio.create_task(can_connect(ip, timeout=timeout)): ip for ip in ips
    }
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                if task.result():
                    for other in pending:
                        other.cancel()
                    return tasks[task]
        return None
    finally:
        for task in pending:
            task.cancel()


class ApiResolver(AbstractResolver):
    """Подменяет адрес api.telegram.org на заранее проверенный IP."""

    def __init__(self, api_ip: str) -> None:
        self.api_ip = api_ip
        self._fallback = None

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> List[ResolveResult]:
        if host == API_HOST:
            return [
                ResolveResult(
                    hostname=host,
                    host=self.api_ip,
                    port=port,
                    family=socket.AF_INET,
                    proto=0,
                    flags=socket.AI_NUMERICHOST,
                )
            ]
        if self._fallback is None:
            from aiohttp.resolver import ThreadedResolver

            self._fallback = ThreadedResolver()
        return await self._fallback.resolve(host, port, family)

    async def close(self) -> None:
        if self._fallback is not None:
            await self._fallback.close()


async def reachable_api_ip() -> str | None:
    ips = candidate_ips(dns_ipv4(API_HOST))
    found = await first_reachable(ips)
    if found is None:
        found = await first_reachable(ips, timeout=6)
    return found
