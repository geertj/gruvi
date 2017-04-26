# Gruvi example program: a cURL like URL downloader

import sys
import argparse
from gruvi.http import HttpClient, parse_url

parser = argparse.ArgumentParser()
parser.add_argument('url')
args = parser.parse_args()

url = parse_url(args.url)

client = HttpClient()
client.connect(url.addr, ssl=url.ssl)
client.request('GET', url.target)

resp = client.getresponse()
if not 200 <= resp.status_code <= 399:
    sys.stderr.write('Error: got status {}\n'.format(resp.status_code))
    sys.exit(1)

charset = resp.charset or 'iso8859-1'

while True:
    buf = resp.body.read(4096)
    if not buf:
        break
    sys.stdout.write(buf.decode(charset))
