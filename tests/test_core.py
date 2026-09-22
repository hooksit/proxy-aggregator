import asyncio
import base64
import json
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.parser import (
    parse_vless, parse_vmess, parse_shadowsocks, parse_trojan, parse_hysteria2,
    extract_configs_from_text, parse_single_link
)
from app.core.singbox import build_singbox_outbound, build_singbox_config

def test_vless_parsing():
    link = "vless://uuid-1234@server.com:443?type=tcp&security=reality&pbk=pubkey123&fp=chrome&sni=server.com&sid=sid123&flow=xtls-rprx-vision#MyVlessNode"
    cfg = parse_vless(link)
    assert cfg is not None
    assert cfg.protocol == "vless"
    assert cfg.server == "server.com"
    assert cfg.port == 443
    assert cfg.uuid == "uuid-1234"
    assert cfg.name == "MyVlessNode"
    
    outbound = build_singbox_outbound(cfg)
    assert outbound["type"] == "vless"
    assert outbound["server"] == "server.com"
    assert outbound["tls"]["reality"]["enabled"] is True
    print("[OK] VLESS parsing & singbox outbound OK")

def test_vmess_parsing():
    vmess_json = json.dumps({
        "v": "2",
        "ps": "MyVMess",
        "add": "vmess.example.com",
        "port": 8443,
        "id": "uuid-5678",
        "net": "ws",
        "path": "/ws",
        "tls": "tls",
        "sni": "vmess.example.com"
    })
    b64 = base64.b64encode(vmess_json.encode()).decode()
    link = f"vmess://{b64}"
    
    cfg = parse_vmess(link)
    assert cfg is not None
    assert cfg.protocol == "vmess"
    assert cfg.server == "vmess.example.com"
    assert cfg.port == 8443
    assert cfg.uuid == "uuid-5678"
    assert cfg.name == "MyVMess"

    outbound = build_singbox_outbound(cfg)
    assert outbound["type"] == "vmess"
    assert outbound["transport"]["type"] == "ws"
    print("[OK] VMess parsing & singbox outbound OK")

def test_shadowsocks_parsing():
    # SIP002 format: ss://base64(method:password)@server:port#name
    userinfo = base64.b64encode(b"chacha20-ietf-poly1305:secretpassword").decode()
    link = f"ss://{userinfo}@ss.example.com:8388#MyShadowsocks"
    
    cfg = parse_shadowsocks(link)
    assert cfg is not None
    assert cfg.protocol == "shadowsocks"
    assert cfg.server == "ss.example.com"
    assert cfg.port == 8388
    assert cfg.password == "secretpassword"
    assert cfg.name == "MyShadowsocks"

    outbound = build_singbox_outbound(cfg)
    assert outbound["type"] == "shadowsocks"
    assert outbound["method"] == "chacha20-ietf-poly1305"
    print("[OK] Shadowsocks parsing & singbox outbound OK")

def test_trojan_parsing():
    link = "trojan://password123@trojan.example.com:443?security=tls&sni=trojan.example.com#MyTrojan"
    cfg = parse_trojan(link)
    assert cfg is not None
    assert cfg.protocol == "trojan"
    assert cfg.server == "trojan.example.com"
    assert cfg.password == "password123"

    outbound = build_singbox_outbound(cfg)
    assert outbound["type"] == "trojan"
    assert outbound["tls"]["enabled"] is True
    print("[OK] Trojan parsing & singbox outbound OK")

def test_hysteria2_parsing():
    link = "hy2://mypassword@hy2.example.com:8443?sni=hy2.example.com&insecure=1#MyHy2"
    cfg = parse_hysteria2(link)
    assert cfg is not None
    assert cfg.protocol == "hysteria2"
    assert cfg.server == "hy2.example.com"
    assert cfg.password == "mypassword"

    outbound = build_singbox_outbound(cfg)
    assert outbound["type"] == "hysteria2"
    assert outbound["tls"]["insecure"] is True
    print("[OK] Hysteria 2 parsing & singbox outbound OK")

def test_multi_extract():
    text = """
    Check out these servers:
    vless://uuid-1@1.1.1.1:443?type=tcp#Node1
    Some random text in telegram channel...
    trojan://pass-2@2.2.2.2:443#Node2
    hy2://pass-3@3.3.3.3:443#Node3
    """
    configs = extract_configs_from_text(text)
    assert len(configs) == 3
    print(f"[OK] Multi-extract successfully found {len(configs)} configs")

async def test_database():
    from app.database import init_db, get_db_connection, get_setting, set_setting, verify_password
    await init_db()
    
    # Check default user
    from app.config import settings
    async with get_db_connection() as db:
        cur = await db.execute("SELECT username, password_hash FROM users WHERE username = ?", (settings.DEFAULT_USERNAME,))
        user = await cur.fetchone()
        assert user is not None
        assert verify_password(settings.DEFAULT_PASSWORD, user["password_hash"])
        print(f"[OK] Admin user '{settings.DEFAULT_USERNAME}' verified")

    # Check default settings
    p_int = await get_setting("parse_interval_hours")
    assert p_int == "12"
    c_int = await get_setting("check_interval_minutes")
    assert c_int == "5"
    st_val = await get_setting("speedtest_enabled")
    assert st_val == "0"
    print("[OK] Default settings verified (12h, 5m, speedtest=0)")

if __name__ == "__main__":
    print("\n--- Running Core Tests ---")
    test_vless_parsing()
    test_vmess_parsing()
    test_shadowsocks_parsing()
    test_trojan_parsing()
    test_hysteria2_parsing()
    test_multi_extract()
    asyncio.run(test_database())
    print("\nALL TESTS PASSED SUCCESSFULLY!")

