"""HTTP control-plane payload for a successfully admitted Prizm player.

Endpoint configuration belongs to the operator. This module does not issue
credentials, authenticate accounts, enable event discovery or bind sockets.
"""

import ipaddress
import re


def endpoint(host, port):
    # ServerEndPoint(string), 0x1B17B58, splits on the last colon and
    # parses the suffix as an Int32. It does not consume a URL.
    if type(host) is not str or not host or host != host.strip():
        raise ValueError('Invalid transport host.')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid transport port.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or any(
                not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                for label in host.split('.')):
            raise ValueError('Invalid transport host.') from None
    return host + ':' + str(port)


def admission_payload(room_id, search_id, tcp_credential, udp_credential,
                      tcp_host, tcp_port, udp_host, udp_port):
    for value in (room_id,search_id,tcp_credential,udp_credential):
        if type(value) is not str or not value or len(value) > 512:
            raise ValueError('Invalid transport admission field.')
    if tcp_credential == udp_credential:
        raise ValueError('TCP and UDP credentials must be distinct.')
    return dict(RoomId=room_id,SearchId=search_id,JwtTcp=tcp_credential,
                JwtUdp=udp_credential,Tcp=endpoint(tcp_host,tcp_port),
                Udp=endpoint(udp_host,udp_port))
