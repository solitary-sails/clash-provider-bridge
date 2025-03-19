# Maintainer: Your Name <your.email@example.com>
pkgname=clash-provider-bridge
pkgver=1.0.0
pkgrel=1
pkgdesc="Clash Proxy Provider Bridge: 将 Clash 配置转换为 proxy-provider 格式"
arch=('x86_64')
#url="https://example.com/clash-provider-bridge"
license=('MIT')
depends=()
makedepends=('pyinstaller' 'python-yaml' 'python-aiohttp')
source=("clash-provider-bridge.py"
        "clash-provider-bridge.service"
        "clash-provider-bridge.sysusers"
        "clash-provider-bridge.tmpfiles"
        "config.cpb.example")
sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP')

build() {
  cd "$srcdir"
  # 使用 pyinstaller 将 Python 脚本打包为独立可执行文件。
  pyinstaller --onefile --name clash-provider-bridge clash-provider-bridge.py
}

package() {
  cd "$srcdir"

  install -Dm755 "dist/clash-provider-bridge" "$pkgdir/usr/bin/clash-provider-bridge"

  install -Dm644 "clash-provider-bridge.service" "$pkgdir/usr/lib/systemd/system/clash_provider_bridge.service"

  install -Dm644 "clash-provider-bridge.sysusers" "$pkgdir/usr/lib/sysusers.d/clash-provider-bridge.conf"
  install -Dm644 "clash-provider-bridge.tmpfiles" "$pkgdir/usr/lib/tmpfiles.d/clash-provider-bridge.conf"

  install -Dm644 "config.cpb.example" "$pkgdir/etc/clash-provider-bridge/config.cpb"
}
