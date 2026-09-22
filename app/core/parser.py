import re
import base64
import json
import hashlib
import urllib.parse
from typing import List, Dict, Any, Optional
import httpx

class ProxyConfig:
    def __init__(
        self,
        protocol: str,
        server: str,
        port: int,
        raw_link: str,
        name: str = "",
        uuid: str = "",
        password: str = "",
        details: Optional[Dict[str, Any]] = None
    ):
        self.protocol = protocol.lower()
        self.server = server.strip()
        self.port = int(port)
        self.raw_link = raw_link.strip()
        self.name = name.strip() or f"{self.protocol.upper()}-{self.server}:{self.port}"
        self.uuid = uuid
        self.password = password
        self.details = details or {}
        self.hash = self.compute_hash()

    def compute_hash(self) -> str:
        ident = f"{self.protocol}://{self.server}:{self.port}:{self.uuid or self.password}"
        return hashlib.sha256(ident.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hash": self.hash,
            "protocol": self.protocol,
            "server": self.server,
            "port": self.port,
            "name": self.name,
            "raw_link": self.raw_link,
            "uuid": self.uuid,
            "password": self.password,
            "details": self.details
        }

def safe_b64decode(s: str) -> str:
    s = s.strip()
    s = s.replace("-", "+").replace("_", "/")
    missing_padding = len(s) % 4
    if missing_padding:
        s += "=" * (4 - missing_padding)
    try:
        return base64.b64decode(s).decode("utf-8", errors="ignore")
    except Exception:
        return ""

def parse_vless(link: str) -> Optional[ProxyConfig]:
    try:
        parsed = urllib.parse.urlparse(link)
        if parsed.scheme.lower() != "vless":
            return None
        
        uuid = parsed.username or ""
        server = parsed.hostname or ""
        port = parsed.port or 443
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else ""
        
        params = dict(urllib.parse.parse_qsl(parsed.query))
        
        return ProxyConfig(
            protocol="vless",
            server=server,
            port=port,
            raw_link=link,
            name=name,
            uuid=uuid,
            details=params
        )
    except Exception:
        return None

def parse_vmess(link: str) -> Optional[ProxyConfig]:
    try:
        b64_part = link[8:] if link.startswith("vmess://") else link
        decoded = safe_b64decode(b64_part)
        if not decoded:
            return None
        
        data = json.loads(decoded)
        server = data.get("add", "")
        port = int(data.get("port", 443))
        uuid = data.get("id", "")
        name = data.get("ps", "")
        
        return ProxyConfig(
            protocol="vmess",
            server=server,
            port=port,
            raw_link=link,
            name=name,
            uuid=uuid,
            details=data
        )
    except Exception:
        return None

def parse_shadowsocks(link: str) -> Optional[ProxyConfig]:
    try:
        parsed = urllib.parse.urlparse(link)
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else ""
        
        # Check if SIP002 format: ss://base64(method:password)@server:port
        if "@" in parsed.netloc:
            user_info, host_port = parsed.netloc.split("@", 1)
            decoded_info = safe_b64decode(user_info)
            if ":" in decoded_info:
                method, password = decoded_info.split(":", 1)
            else:
                method, password = "aes-256-gcm", decoded_info
            
            host, port_str = host_port.split(":", 1)
            port = int(port_str)
        else:
            # Entire netloc is base64(method:password@server:port)
            decoded = safe_b64decode(parsed.netloc)
            if "@" in decoded:
                user_info, host_port = decoded.split("@", 1)
                method, password = user_info.split(":", 1)
                host, port_str = host_port.split(":", 1)
                port = int(port_str)
            else:
                return None
        
        params = dict(urllib.parse.parse_qsl(parsed.query))
        params["method"] = method
        
        return ProxyConfig(
            protocol="shadowsocks",
            server=host,
            port=port,
            raw_link=link,
            name=name,
            password=password,
            details=params
        )
    except Exception:
        return None

def parse_trojan(link: str) -> Optional[ProxyConfig]:
    try:
        parsed = urllib.parse.urlparse(link)
        password = parsed.username or ""
        server = parsed.hostname or ""
        port = parsed.port or 443
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else ""
        params = dict(urllib.parse.parse_qsl(parsed.query))
        
        return ProxyConfig(
            protocol="trojan",
            server=server,
            port=port,
            raw_link=link,
            name=name,
            password=password,
            details=params
        )
    except Exception:
        return None

def parse_hysteria2(link: str) -> Optional[ProxyConfig]:
    try:
        parsed = urllib.parse.urlparse(link)
        password = parsed.username or ""
        server = parsed.hostname or ""
        port = parsed.port or 443
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else ""
        params = dict(urllib.parse.parse_qsl(parsed.query))
        
        return ProxyConfig(
            protocol="hysteria2",
            server=server,
            port=port,
            raw_link=link,
            name=name,
            password=password,
            details=params
        )
    except Exception:
        return None

def parse_single_link(link: str) -> Optional[ProxyConfig]:
    link = link.strip()
    if not link:
        return None
    
    lower = link.lower()
    if lower.startswith("vless://"):
        return parse_vless(link)
    elif lower.startswith("vmess://"):
        return parse_vmess(link)
    elif lower.startswith("ss://"):
        return parse_shadowsocks(link)
    elif lower.startswith("trojan://"):
        return parse_trojan(link)
    elif lower.startswith("hy2://") or lower.startswith("hysteria2://"):
        return parse_hysteria2(link)
    return None

def extract_configs_from_text(content: str) -> List[ProxyConfig]:
    results = []
    seen_hashes = set()
    
    # Check if the content is entirely base64 encoded
    decoded_content = safe_b64decode(content)
    if decoded_content and any(proto in decoded_content for proto in ["vless://", "vmess://", "ss://", "trojan://", "hy2://", "hysteria2://"]):
        content = decoded_content
    
    # Regex to find all matching links
    pattern = re.compile(r'((?:vless|vmess|ss|trojan|hy2|hysteria2)://[^\s<>"\'`]+)', re.IGNORECASE)
    matches = pattern.findall(content)
    
    for match in matches:
        cfg = parse_single_link(match)
        if cfg and cfg.hash not in seen_hashes:
            seen_hashes.add(cfg.hash)
            results.append(cfg)
            
    return results

async def fetch_source_content(url: str, timeout: float = 15.0) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }
    
    # If it's a telegram channel link like t.me/channel -> convert to t.me/s/channel (public web preview)
    if "t.me/" in url and not "t.me/s/" in url:
        url = url.replace("t.me/", "t.me/s/")
    
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text
