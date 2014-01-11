# Example: cURL like URL downloader

import sys
import argparse
from gruvi import http

parser = argparse.ArgumentParser()
parser.add_argument('url');
args = parser.parse_args()

url = http.urlsplit2(args.url)
client = http.HttpClient()
client.connect((url.hostname, url.port), ssl=url.scheme == 'https')

client.request('GET', url.path)
response = client.getresponse()

ctype = response.get_header('Content-Type', 'text/plain')
ctype, options = http.split_header_options(ctype)
if not ctype.startswith('text/'):
    print('Refusing to write {} to stdout'.format(ctype))
    sys.exit(0)
charset = options.get('charset', 'iso-8859-1')

while True:
    buf = response.read(4096)
    if not buf:
        break
    sys.stdout.write(buf.decode(charset))
