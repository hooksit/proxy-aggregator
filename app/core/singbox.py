import json
import shutil
import asyncio
import socket
from typing import Dict, Any, Optional
from app.core.parser import ProxyConfig
from app.config import settings

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def build_singbox_outbound(cfg: ProxyConfig) -> Dict[str, Any]:
    proto = cfg.protocol.lower()
    details = cfg.details or {}
    
    outbound: Dict[str, Any] = {
        "tag": "proxy",
        "server": cfg.server,
        "server_port": cfg.port
    }
    
    if proto == "vless":
        outbound["type"] = "vless"
        outbound["uuid"] = cfg.uuid
        flow = details.get("flow", "")
        if flow:
            outbound["flow"] = flow
            
        sec = details.get("security", "")
        if sec in ["tls", "reality"]:
            tls_cfg: Dict[str, Any] = {"enabled": True}
            sni = details.get("sni") or details.get("serverNames") or cfg.server
            tls_cfg["server_name"] = sni
            
            fp = details.get("fp", "chrome")
            if fp:
                tls_cfg["utls"] = {"enabled": True, "fingerprint": fp}
                
            if sec == "reality":
                tls_cfg["reality"] = {
                    "enabled": True,
                    "public_key": details.get("pbk", ""),
                    "short_id": details.get("sid", "")
                }
            outbound["tls"] = tls_cfg
            
        net_type = details.get("type", "tcp").lower()
        if net_type in ["ws", "websocket"]:
            outbound["transport"] = {
                "type": "ws",
                "path": details.get("path", "/"),
                "headers": {"Host": details.get("host", sni if 'sni' in locals() else cfg.server)}
            }
        elif net_type == "grpc":
            outbound["transport"] = {
                "type": "grpc",
                "service_name": details.get("serviceName", "")
            }

    elif proto == "vmess":
        outbound["type"] = "vmess"
        outbound["uuid"] = cfg.uuid
        outbound["alter_id"] = int(details.get("aid", 0))
        outbound["security"] = "auto"
        
        tls_val = details.get("tls", "")
        if tls_val == "tls":
            outbound["tls"] = {
                "enabled": True,
                "server_name": details.get("sni") or details.get("host") or cfg.server
            }
            
        net = details.get("net", "tcp").lower()
        if net in ["ws", "websocket"]:
            outbound["transport"] = {
                "type": "ws",
                "path": details.get("path", "/"),
                "headers": {"Host": details.get("host", "")}
            }
        elif net == "grpc":
            outbound["transport"] = {
                "type": "grpc",
                "service_name": details.get("path", "")
            }

    elif proto == "shadowsocks":
        outbound["type"] = "shadowsocks"
        outbound["method"] = details.get("method", "aes-256-gcm")
        outbound["password"] = cfg.password

    elif proto == "trojan":
        outbound["type"] = "trojan"
        outbound["password"] = cfg.password
        sni = details.get("sni") or cfg.server
        outbound["tls"] = {
            "enabled": True,
            "server_name": sni
        }
        net_type = details.get("type", "tcp").lower()
        if net_type in ["ws", "websocket"]:
            outbound["transport"] = {
                "type": "ws",
                "path": details.get("path", "/"),
                "headers": {"Host": details.get("host", sni)}
            }
        elif net_type == "grpc":
            outbound["transport"] = {
                "type": "grpc",
                "service_name": details.get("serviceName", "")
            }

    elif proto in ["hy2", "hysteria2"]:
        outbound["type"] = "hysteria2"
        outbound["password"] = cfg.password
        sni = details.get("sni") or cfg.server
        insecure = details.get("insecure") in ["1", "true", True]
        outbound["tls"] = {
            "enabled": True,
            "server_name": sni,
            "insecure": insecure
        }
        obfs_type = details.get("obfs")
        obfs_pass = details.get("obfs-password")
        if obfs_type and obfs_pass:
            outbound["obfs"] = {
                "type": obfs_type,
                "password": obfs_pass
            }

    return outbound

def build_singbox_config(outbound: Dict[str, Any], in_port: int) -> Dict[str, Any]:
    return {
        "log": {
            "disabled": True,
            "level": "panic"
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": in_port
            }
        ],
        "outbounds": [
            outbound,
            {
                "type": "direct",
                "tag": "direct"
            }
        ],
        "route": {
            "final": "proxy",
            "auto_detect_interface": True
        }
    }

def get_singbox_executable() -> Optional[str]:
    # Check configured path first
    if shutil.which(settings.SINGBOX_PATH):
        return settings.SINGBOX_PATH
    # Check default common paths
    for p in ["sing-box", "sing-box.exe", "/usr/local/bin/sing-box", "/usr/bin/sing-box"]:
        if shutil.which(p):
            return p
    return None
