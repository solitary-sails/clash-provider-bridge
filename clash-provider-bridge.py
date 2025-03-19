#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import ssl
import sys
import yaml
from aiohttp import web, ClientSession
#import aiohttp

# 全局配置对象
config = {}
# 使用 dict 存储各订阅对应的 asyncio Lock，防止并发写cache文件
subscription_locks = {}

async def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg


def ensure_cache_dir(cache_dir):
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)


def convert_subscription(raw_content):
    """
    示例转换逻辑：在内容前加入描述头部。根据实际需要调整转换逻辑。
    """
    try:
        data = yaml.safe_load(raw_content)
    except Exception as e:
        return f"解析配置失败: {e}"

    if not isinstance(data, dict):
        return "无效的 Clash 配置：格式不正确"

    proxies = data.get("proxies")
    if not proxies:
        return "无效的 Clash 配置：未找到 'proxies' 字段"

    provider_config = {"proxies": proxies}
    try:
        # 返回 YAML 格式字符串
        return yaml.dump(provider_config, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception as e:
        return f"转换为 YAML 输出失败: {e}"


async def update_subscription(subscription, cache_dir, session: ClientSession):
    """
    访问订阅链接、转换内容、写入缓存文件。
    """
    subname = subscription.get("subname")
    url = subscription.get("url")
    if not subname or not url:
        print(f"[ERROR] Subscription missing subname or url: {subscription}")
        return

    headers = {"User-Agent": "clash-meta"}
    try:
        print(f"[INFO] Fetching subscription '{subname}' from {url} ...")
        async with session.get(url, timeout=10, headers=headers) as resp:
            if resp.status != 200:
                print(f"[ERROR] Failed to fetch {url}: HTTP {resp.status}")
                return
            content = await resp.text()
        converted = convert_subscription(content)
        # 保证写文件的操作串行
        lock = subscription_locks.setdefault(subname, asyncio.Lock())
        async with lock:
            fname = os.path.join(cache_dir, f"{subname}.provider")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(converted)
        print(f"[INFO] Subscription '{subname}' updated, saved to {fname}")
    except Exception as e:
        print(f"[ERROR] Exception updating subscription '{subname}': {e}")


async def subscription_updater(subscription, cache_dir):
    """
    后台任务定时刷新某个订阅
    """
    refresh_interval = subscription.get("refresh_interval", 3600)
    async with ClientSession() as session:
        # 先更新一次
        await update_subscription(subscription, cache_dir, session)
        while True:
            await asyncio.sleep(refresh_interval)
            await update_subscription(subscription, cache_dir, session)


async def handle_subscription(request):
    """
    处理订阅请求，URL 格式为 /{subname}[?token=xxx]
    """
    subname = request.match_info.get('subname')
    # 若配置了 token，则需要校验
    token_required = config.get("token")
    if token_required:
        token = request.query.get("token")
        if token != token_required:
            return web.Response(status=403, text="Forbidden: Invalid token")
    cache_dir = config.get("cache_dir", "/etc/clash-provider-bridge/cache")
    fname = os.path.join(cache_dir, f"{subname}.provider")
    if not os.path.exists(fname):
        return web.Response(status=404, text="Subscription not found")
    try:
        lock = subscription_locks.setdefault(subname, asyncio.Lock())
        # 使用 lock 防止和更新任务冲突
        async with lock:
            with open(fname, "r", encoding="utf-8") as f:
                content = f.read()
        return web.Response(text=content, content_type="text/plain")
    except Exception as e:
        print(f"[ERROR] Failed to read file {fname}: {e}")
        return web.Response(status=500, text="Internal Server Error")


async def init_app():
    app = web.Application()
    # 路由：所有的订阅需求通过 /{subname} 匹配
    app.router.add_get("/{subname}", handle_subscription)
    return app


async def main():
    parser = argparse.ArgumentParser(description="Clash Proxy Provider Bridge (aiohttp version)")
    parser.add_argument("-c", "--config", default="/etc/clash-provider-bridge/config.cpb",
                        help="指定配置文件路径，默认：/etc/clash-provider-bridge/config.cpb")
    # 可选的 IP 与端口覆写参数
    parser.add_argument("--ip", help="外部提供服务监听 IP 覆写")
    parser.add_argument("--port", type=int, help="外部提供服务监听端口覆写")
    # 可选的 HTTPS 参数，如果希望启用 TLS，则提供证书和私钥文件路径（必须同时提供）
    parser.add_argument("--certfile", help="HTTPS 证书文件路径")
    parser.add_argument("--keyfile", help="HTTPS 私钥文件路径")
    args = parser.parse_args()

    global config
    try:
        config = await load_config(args.config)
    except Exception as e:
        print(f"[ERROR] 加载配置文件失败: {e}")
        sys.exit(1)

    # 命令行中指定了 ip, port，则覆写配置文件中的值
    if args.ip:
        config["listen_ip"] = args.ip
    if args.port:
        config["listen_port"] = args.port

    cache_dir = config.get("cache_dir", "/etc/clash-provider-bridge/cache")
    ensure_cache_dir(cache_dir)

    # 针对每个订阅项启动后台刷新任务
    subscriptions = config.get("subscriptions", [])
    for subscription in subscriptions:
        # 为了第一次能较快更新，采用 create_task 产生后台任务
        asyncio.create_task(subscription_updater(subscription, cache_dir))

    app = await init_app()
    listen_ip = config.get("listen_ip", "0.0.0.0")
    listen_port = config.get("listen_port", 8000)

    ssl_context = None
    if args.certfile and args.keyfile:
        try:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(certfile=args.certfile, keyfile=args.keyfile)
            print(f"[INFO] 启用 HTTPS 模式")
        except Exception as e:
            print(f"[ERROR] 初始化 SSL 失败: {e}")
            sys.exit(1)
    else:
        print(f"[INFO] 仅启用 HTTP 模式，如需 HTTPS 请传入 --certfile 与 --keyfile 参数")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, listen_ip, listen_port, ssl_context=ssl_context)
    print(f"[INFO] HTTP{'S' if ssl_context else ''} Server starting on {listen_ip}:{listen_port} ...")
    await site.start()

    # 阻塞等待
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("[INFO] 收到退出指令，正在关闭...")
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
