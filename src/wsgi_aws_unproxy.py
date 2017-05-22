"""
WSGI middleware that makes sure that ``REMOTE_ADDR``
points to the actual client, and not the AWS loadbalancer.

This is needed for proper IP logging, Sentry error reporting,
and potential rate limiting.
"""
import logging

import requests
from netaddr import AddrFormatError, IPNetwork


class UnProxy(object):
    def __init__(self, app):
        self._app = app
        self._allowed_proxy_ips = self._load_allowed_ips()

    def __call__(self, environ, start_response):
        remote_addr = environ.get('REMOTE_ADDR')
        x_forwarded_for = environ.get('HTTP_X_FORWARDED_FOR')

        if x_forwarded_for:
            forwarded_ips = [v.strip() for v in x_forwarded_for.split(',')]

            while self._is_proxy_ip(remote_addr) and forwarded_ips:
                remote_addr = forwarded_ips.pop()

            x_forwarded_for = ", ".join(forwarded_ips)
            _env_set(environ, 'REMOTE_ADDR', remote_addr)
            _env_set(environ, 'HTTP_X_FORWARDED_FOR', x_forwarded_for)
        return self._app(environ, start_response)

    def _is_proxy_ip(self, ip):
        try:
            for addr in self._allowed_proxy_ips:
                if ip in addr:
                    return True
            return False
        except AddrFormatError:
            return False

    def _load_allowed_ips(self):
        """Retrieve the cloudfront ip's from amazon"""

        # Base
        values = [
            '10.0.0.0/8',
            '172.16.0.0/20',
            '192.168.0.0/16',
        ]

        session = requests.session()
        session.mount('http://', requests.adapters.HTTPAdapter(max_retries=5))
        session.mount('https://', requests.adapters.HTTPAdapter(max_retries=5))

        # Cloudfront
        try:
            resp = session.get('https://ip-ranges.amazonaws.com/ip-ranges.json')
        except requests.ConnectionError:
            logger = logging.getLogger(__name__)
            logger.exception("Unable to retrieve AWS ip ranges")
            return []

        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                logger = logging.getLogger(__name__)
                logger.exception("Unable to retrieve AWS ip ranges")
                return []

            values.extend([
                x['ip_prefix'] for x in data['prefixes']
                if x['service'] == 'CLOUDFRONT'
            ])
        return [IPNetwork(addr) for addr in values]


def _env_set(environ, key, value):
    """ Sets or deletes the given key in the environ dict. """
    if value:
        environ[key] = value
    elif key in environ:
        del environ[key]
