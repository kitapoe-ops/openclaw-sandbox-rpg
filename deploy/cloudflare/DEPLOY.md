# Hybrid Deployment Guide
## Vercel (Frontend) + Local Docker (Backend) + Cloudflare Tunnels

### 架構

```
                     Internet
                        |
                  Cloudflare Edge
                  (WAF + DDoS + SSL)
                        |
              api.yourdomain.com (Tunnel)
                        |
              +---------+---------+
              |                   |
        Vercel CDN         Local Docker
        (Frontend)         (Backend)
              |                   |
        openclaw-rpg          FastAPI :8000
        .vercel.app           + Postgres
                              + LanceDB
                              + LLM (local)
```

### 零成本估算

| 組件 | 費用 |
|------|------|
| Vercel (Hobby plan) | $0 |
| Cloudflare Tunnels (Free) | $0 |
| Cloudflare DNS | $0 |
| 本地硬體 | 已有 |
| LLM API (M3) | 按用量 |
| LLM 本地 (Qwen) | $0 |
| **總計** | **~$0/月 + API 費用** |

### 前端：Vercel 部署

```bash
# 1. 安裝 Vercel CLI
npm i -g vercel

# 2. 喺 frontend/ 目錄
cd frontend

# 3. 設定環境變數
echo "VITE_API_BASE_URL=https://api.yourdomain.com" > .env.production
echo "VITE_WS_BASE_URL=wss://api.yourdomain.com" >> .env.production

# 4. 部署
vercel --prod
```

Vercel 會自動：
- 跑 `npm run build`
- 分配 `https://openclaw-rpg-xxx.vercel.app` 網址
- 配 GitHub CI/CD（push 即 deploy）

### 後端：本地 Docker

```bash
# 1. Clone repo
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git
cd openclaw-sandbox-rpg

# 2. 配置環境變數
cp .env.example .env
# 編輯 .env，填寫 LLM API key 等

# 3. 啟動後端
docker-compose up -d

# 4. 載入世界包（首次）
docker exec -it sandbox-rpg-backend python -m backend.scripts.load_world worlds/dnd_5e_forgotten_realms.yaml

# 5. 驗證
curl http://localhost:8000/health
```

預期回應：
```json
{
  "status": "ok",
  "version": "0.3.0",
  "registry": {"active_characters": 0, "total_connections": 0},
  "scene_locks": {"total_locks": 0, "active_locks": 0}
}
```

### Cloudflare Tunnel 設定

#### 步驟 1：建立 Cloudflare 帳號

https://dash.cloudflare.com/sign-up （免費）

#### 步驟 2：新增網域到 Cloudflare

（如果你有網域，例如 `yourdomain.com`）

如果冇網域，可以用 Cloudflare 提供的：
- `*.trycloudflare.com`（每次啟動隨機網址）
- 或者買個平價 domain（~$10/年）

#### 步驟 3：安裝 cloudflared

**macOS:**
```bash
brew install cloudflare/cloudflare/cloudflared
```

**Linux (Debian/Ubuntu):**
```bash
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg.pub >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared focal main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install cloudflared
```

**Windows:**
下載：https://github.com/cloudflare/cloudflared/releases

#### 步驟 4：認證 + 建立 Tunnel

```bash
# 登入
cloudflared tunnel login

# 建立 tunnel
cloudflared tunnel create openclaw-rpg

# 記下輸出嘅 TUNNEL_ID（例如：a1b2c3d4-...）
# 記下 credentials file 位置（例如：~/.cloudflared/<TUNNEL_ID>.json）
```

#### 步驟 5：配置

```bash
# 複製範本
cp deploy/cloudflare/config.yml.example ~/.cloudflared/config.yml

# 編輯
nano ~/.cloudflared/config.yml
```

填入：
- `tunnel: <TUNNEL_ID>` （步驟 4 嘅 ID）
- `credentials-file: /home/YOUR_USER/.cloudflared/<TUNNEL_ID>.json`（實際路徑）
- `hostname: api.yourdomain.com`（你嘅網域）

#### 步驟 6：配置 DNS

```bash
cloudflared tunnel route dns openclaw-rpg api.yourdomain.com
```

#### 步驟 7：啟動 Tunnel

```bash
cloudflared tunnel run openclaw-rpg
```

驗證：
```bash
curl https://api.yourdomain.com/health
```

應該見到 JSON response。

#### 步驟 8：設定為 Systemd Service（永久運行）

```bash
# Linux
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
sudo systemctl status cloudflared
```

### 故障排除

#### WS 連不上？

1. Check CORS：FastAPI CORS middleware 允許 `https://*.vercel.app`
2. Check WS URL：前端用 `wss://`（HTTPS），唔係 `ws://`
3. Check firewall：本地 8000 port 唔需要對外開放，cloudflared 會處理

#### Tunnel 啟動失敗？

```bash
cloudflared tunnel run openclaw-rpg --loglevel debug
```

#### Vercel 部署失敗？

1. Check `frontend/package.json` 嘅 `build` script
2. Check `frontend/vite.config.ts` 嘅 `base: '/'`
3. Check Vercel build logs

### 安全性檢查清單

- [x] Cloudflare WAF 啟用
- [x] Cloudflare DDoS 防護
- [x] 本地 IP 隱藏（只暴露 Cloudflare 邊緣）
- [x] HTTPS / SSL 自動配發
- [x] FastAPI CORS 限制 origin
- [ ] TODO: JWT auth token
- [ ] TODO: Rate limiting
- [ ] TODO: Request size limits
