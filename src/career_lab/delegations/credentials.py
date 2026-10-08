"""Explicit, private configuration. Tokens never appear in argv or repr."""
from dataclasses import dataclass,field
from pathlib import Path
import json,os,stat
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Credentials:
    api_url: str
    session_id: str
    token: str=field(repr=False)


def load_credentials(path):
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_uid!=os.getuid():raise ValueError('private configuration required')
        raw=os.read(fd,16385)
    finally:os.close(fd)
    if len(raw)>16384:raise ValueError('configuration too large')
    value=json.loads(raw)
    if not isinstance(value,dict) or set(value)!={'api_url','session_id','token'} or any(not isinstance(x,str) or not x for x in value.values()):raise ValueError('invalid configuration')
    url=urlsplit(value['api_url'])
    if url.username or url.password or url.query or url.fragment or any(ord(c)<32 for c in value['api_url']):raise ValueError('invalid API URL')
    if url.scheme!='https' and not (url.scheme=='http' and url.hostname in {'127.0.0.1','localhost','::1'}):raise ValueError('HTTPS or loopback required')
    if not url.hostname or len(value['token'])>4096 or '\n' in value['token'] or any(c in value['token'] for c in '\r\n') or any(c in value['session_id'] for c in '/\\%\r\n') or value['session_id'] in {'.','..'}:raise ValueError('invalid configuration')
    return Credentials(value['api_url'].rstrip('/'),value['session_id'],value['token'])


def redact(value,token):
    if isinstance(value,str):return value.replace(token,'[REDACTED]') if token else value
    if isinstance(value,list):return [redact(x,token) for x in value]
    if isinstance(value,dict):return {k:('[REDACTED]' if k.lower() in {'token','authorization','api_key','access_token','refresh_token'} else redact(v,token)) for k,v in value.items()}
    return value
