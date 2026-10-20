"""Client for worldserver's SOAP endpoint (SOAP.Enabled / SOAP.IP / SOAP.Port in worldserver.conf).

Behaviour of the server side (src/server/apps/worldserver/ACSoap/ACSoap.cpp):
  * HTTP basic auth with a game account; unknown user / wrong password -> HTTP 401,
    account below GM level 3 (SEC_ADMINISTRATOR) -> HTTP 403.
  * The command runs in the world thread; success -> <result>output</result>,
    failure -> SOAP fault whose faultstring is the command's output.
  * One request is handled at a time.
"""
from __future__ import annotations

import asyncio
import base64
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

_ENVELOPE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">'
    "<SOAP-ENV:Body><ns1:executeCommand><command>{command}</command></ns1:executeCommand></SOAP-ENV:Body>"
    "</SOAP-ENV:Envelope>"
)


class SoapError(Exception):
    """SOAP is set up but refused the request (credentials, permissions, bad response)."""


class SoapUnavailable(SoapError):
    """Nothing answers on the SOAP port (disabled, worldserver not up yet, wrong port)."""


def _find_text(xml: bytes, tag: str) -> str | None:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag:
            return el.text or ""
    return None


def _execute(host: str, port: int, username: str, password: str, command: str, timeout: float) -> tuple[bool, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"http://{host}:{port}/",
        data=_ENVELOPE.format(command=escape(command)).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "urn:AC#executeCommand",
                 "Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
        result = _find_text(body, "result")
        if result is None:
            raise SoapError("Unexpected SOAP response from worldserver.")
        return True, result.strip()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SoapError("SOAP login failed: wrong account name or password (Settings → SOAP).") from exc
        if exc.code == 403:
            raise SoapError("The SOAP account needs GM level 3 (Administrator).") from exc
        fault = _find_text(exc.read(), "faultstring")
        if fault is not None:
            return False, fault.strip()   # the command ran and failed; its output explains why
        raise SoapError(f"SOAP request failed with HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise SoapUnavailable(f"Worldserver SOAP is not reachable on {host}:{port}.") from exc


async def execute(host: str, port: int, username: str, password: str, command: str,
                  timeout: float = 15.0) -> tuple[bool, str]:
    """Run a GM command. Returns (succeeded, output)."""
    return await asyncio.to_thread(_execute, host, port, username, password, command, timeout)
