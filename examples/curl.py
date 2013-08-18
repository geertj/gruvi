# Example: cURL like URL downloader

import sys
import logging
import argparse
from gruvi.http import HttpClient, geturlinfo

logging.basicConfig()

parser = argparse.ArgumentParser()
parser.add_argument('url');
args = parser.parse_args()

client = HttpClient()
host, port, ssl, path = geturlinfo(args.url)
client.connect((host, port), ssl=ssl)

client.request('GET', path)
response = client.getresponse()

while True:
    buf = response.read(4096)
    if not buf:
        break
    print(buf)
