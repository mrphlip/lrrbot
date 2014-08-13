#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from config import config
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
from Crypto.Hash import SHA256
import twitch
import socket
import json
import time
import base64
import utils
import xml.dom
import xml.dom.minidom
import dateutil.parser

SPREADSHEET = "1yrf6d7dPyTiWksFkhISqEc-JR71dxZMkUoYrX4BR40Y"

def base64_encode(data):
    return base64.urlsafe_b64encode(data).strip(b"=")

def send_bot_command(command, param):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(config["socket_filename"])
    data = {
        "command": command,
        "param": param,
        "user": "lrrbot"
    }
    conn.send((json.dumps(data)+"\n").encode())
    buf = b""
    while b"\n" not in buf:
        buf += conn.recv(1024)
    return json.loads(buf.decode())

def get_oauth_token(scopes):
    with open("keys.json") as f:  
        keys = json.load(f)
    t = int(time.time())

    header = json.dumps({"alg":"RS256", "typ":"JWT"}).encode("utf-8")
    claim = json.dumps({
        "iss": keys["client_email"],
        "scope": " ".join(scopes),
        "aud": "https://accounts.google.com/o/oauth2/token",
        "iat": t,  
        "exp": t+60*60,
    }).encode("utf-8")

    data = base64_encode(header) + b'.' + base64_encode(claim)

    key = RSA.importKey(keys["private_key"])
    h = SHA256.new(data)
    signer = PKCS1_v1_5.new(key)
    signature = signer.sign(h)

    jwt = (data + b'.' + base64_encode(signature)).decode("utf-8")

    data = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}

    ret = json.loads(utils.http_request("https://accounts.google.com/o/oauth2/token", data, "POST"))
    if "error" in ret:
        raise Exception(ret["error"])
    return ret

def find_schema(root, schema):
    for link in root.getElementsByTagName("link"):
        if link.attributes["rel"].value == schema:
            return link.attributes["href"].value

def new_field(doc, name, value):
    name = "gsx:"+"".join(filter(str.isalnum, name)).lower()
    node = doc.createElement(name)
    node.appendChild(doc.createTextNode(value))
    return node

VIDEO_CACHE = {}

def twitch_videos():
    next_data = {"start": 0, "limit": 10, "broadcasts": "true"}
    last_length = 1
    while last_length > 0:
        if next_data["start"] in VIDEO_CACHE:
            videos = VIDEO_CACHE[next_data["start"]]
        else:
            videos = json.loads(utils.http_request("https://api.twitch.tv/kraken/channels/%s/videos" % config["channel"], data = next_data))["videos"]
            VIDEO_CACHE[next_data["start"]] = videos
        last_length = len(next_data)
        for video in videos:
            yield video
        next_data["start"] += next_data["limit"]
        last_length = len(videos)

def twitch_lookup(highlight):
    for video in twitch_videos():
        t = dateutil.parser.parse(video["recorded_at"]).timestamp()
        print(video["title"], t, t+video["length"])
        if highlight["time"] < t:
            continue
        elif highlight["time"] > t+video["length"]:
            return None
        else:
            highlight["title"] = video["title"]
            highlight["time"] = highlight["time"] - t
            highlight["url"] = video["url"]
            return highlight

def main():
    if twitch.get_info()["live"]:
        print("Stream is live.")
        return
    
    highlights = send_bot_command("get_data", {"key": "staged_highlights"})
    send_bot_command("set_data", {"key": "staged_highlights", "value": []})
    if highlights is None:
        highlights = []
    highlights = list(filter(lambda e: e is not None, map(twitch_lookup, highlights)))

    if highlights == []:
        return

    token = get_oauth_token(["https://spreadsheets.google.com/feeds"])
    headers = {"Authorization": "%(token_type)s %(access_token)s" % token}
    url = "https://spreadsheets.google.com/feeds/worksheets/%s/private/full" % SPREADSHEET
    tree = xml.dom.minidom.parseString(utils.http_request(url, headers=headers))
    worksheet = next(iter(tree.getElementsByTagName("entry")))
    list_feed = find_schema(worksheet, "http://schemas.google.com/spreadsheets/2006#listfeed")
    if list_feed is None:
        print("List feed missing.")
        return
    list_feed = xml.dom.minidom.parseString(utils.http_request(list_feed, headers=headers))
    post_url = find_schema(list_feed, "http://schemas.google.com/g/2005#post")
    if post_url is None:
        print("POST URL missing.")
        return

    for highlight in highlights:
        doc = xml.dom.minidom.getDOMImplementation().createDocument(None, "entry", None)
        root = doc.documentElement
        root.setAttribute("xmlns", "http://www.w3.org/2005/Atom")
        root.setAttribute("xmlns:gsx", "http://schemas.google.com/spreadsheets/2006/extended")

        root.appendChild(new_field(doc, "SHOW", highlight["title"]))
        root.appendChild(new_field(doc, "QUOTE or MOMENT", highlight["description"]))
        root.appendChild(new_field(doc, "YOUTUBE VIDEO LINK", highlight["url"]))
        root.appendChild(new_field(doc, "ROUGH TIME THEREIN", "before "+utils.nice_duration(highlight["time"], 0)))
        root.appendChild(new_field(doc, "NOTES", "From chat user '%s'." % highlight["user"]))

        headers["Content-Type"] = "application/atom+xml"
        utils.http_request(post_url, headers=headers, data=doc.toxml(), method="POST")

if __name__ == '__main__':
    main()
