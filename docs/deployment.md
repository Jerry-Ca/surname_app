# 部署说明（大陆地域服务器 + 公网 IP）

对应任务 **E-05**，三天阶段的部署方案。域名、备案与 HTTPS 属于期末工作。
配套文件：[../deploy/README.md](../deploy/README.md)、[../deploy/nginx/surname_app.conf](../deploy/nginx/surname_app.conf)、[../deploy/systemd/surname-backend.service](../deploy/systemd/surname-backend.service)

## 1. 服务器准备

| 项目 | 三天要求 |
| --- | --- |
| 规格 | 大陆地域轻量应用服务器，2 核 4GB 起步 |
| 系统 | Ubuntu 22.04 / 24.04（示例按 Ubuntu 写） |
| 端口 | 只开放 **80**、**443**、**22** |
| 数据库 | 装在服务器本机，**不暴露公网**（只监听 127.0.0.1） |
| 访问方式 | 公网 IP + HTTP 同源访问（先能用 IP 打开网页） |

```bash
# 系统依赖
sudo apt update && sudo apt install -y python3.12 python3.12-venv postgresql nginx git
sudo systemctl enable --now postgresql nginx
```

## 2. 代码与虚拟环境

```bash
sudo mkdir -p /srv/surname_app && sudo chown $USER /srv/surname_app
git clone https://github.com/Jerry-Ca/surname_app.git /srv/surname_app
cd /srv/surname_app/backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## 3. 环境变量（**唯一**的密钥入口）

```bash
sudo tee /etc/surname_app.env >/dev/null <<'EOF'
DATABASE_URL=postgresql+psycopg://surname:CHANGE_ME@127.0.0.1:5432/surname_app
DEEPSEEK_API_KEY=CHANGE_ME
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
ADMIN_TOKEN=CHANGE_ME
APP_ENV=production
API_PORT=8000
EOF
sudo chmod 600 /etc/surname_app.env
```

- 文件权限 600，属主为运行服务的账号。
- **禁止**把 Key 写进仓库、写进前端、写进 systemd 单元文件（用 `EnvironmentFile`）。
- `ADMIN_TOKEN` 用于 `/api/admin/*`，只发给 B 与 C。

## 4. 数据库初始化

```bash
sudo -u postgres psql <<'SQL'
CREATE USER surname WITH PASSWORD 'CHANGE_ME';
CREATE DATABASE surname_app OWNER surname;
\c surname_app
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgvector;   -- 失败不阻塞，走 JSON 向量降级
SQL
```

```bash
cd /srv/surname_app/migrations && alembic upgrade head
cd /srv/surname_app && python scripts/import_data.py --file data/verified/evidences.csv --operator B
curl -s http://127.0.0.1:8000/api/admin/reindex -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' -d '{"mode":"all"}'
```

## 5. 后端进程（systemd）

```bash
sudo cp /srv/surname_app/deploy/systemd/surname-backend.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now surname-backend
systemctl status surname-backend
curl -s http://127.0.0.1:8000/api/health
```

健康检查返回 `status=ok` 且 `database.connected=true` 才算成功；`status=degraded` 时先确认模型与向量配置。

## 6. 前端构建与反向代理

```bash
cd /srv/surname_app/frontend && npm ci && npm run build      # 产物在 frontend/dist
sudo cp /srv/surname_app/deploy/nginx/surname_app.conf /etc/nginx/sites-available/surname_app
sudo ln -sf /etc/nginx/sites-available/surname_app /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Nginx 负责：静态文件（`dist`）、`/api` 反代到 `127.0.0.1:8000`、`/api/admin` 额外做来源 IP 限制。同源访问意味着前端不需要 CORS 配置。

## 7. 备份与恢复（C-06）

```bash
python scripts/backup_db.py --out /srv/backups            # 产出带时间戳的 dump + 校验和
python scripts/restore_db.py --file /srv/backups/xxx.dump --yes   # 在空库上恢复
```

每天至少手动备份一次；Day3 演示前必须备份一次并把 dump 交一份给 A。

服务器上建议加一条定时任务（三天阶段用 cron 即可）：

```bash
0 3 * * * cd /srv/surname_app && /srv/surname_app/backend/.venv/bin/python scripts/backup_db.py --out /srv/backups >> /var/log/surname_backup.log 2>&1
```

## 8. 上线自检清单

- [ ] `sudo ufw status` 只允许 22/80/443；`ss -lntp` 确认 5432 未监听公网
- [ ] `curl http://<公网IP>/api/health` 返回 200，`database.connected=true`
- [ ] 从手机 4G 网络打开 `http://<公网IP>/`，完成一次完整查询
- [ ] 前端构建产物中不含任何 `DEEPSEEK` / `EMBEDDING` 字样（`grep -r "DEEPSEEK" frontend/dist` 应为空）
- [ ] 服务重启（`sudo reboot`）后自动拉起，数据与索引仍在
- [ ] 拔掉模型 Key 后重启，页面结构化功能仍可用
- [ ] 备份文件存在且校验和匹配

## 9. 回滚

```bash
sudo systemctl stop surname-backend
python scripts/restore_db.py --file /srv/backups/<上一个可用dump> --yes
cd /srv/surname_app && git checkout <上一个可用tag>   # 例 v1.0.0
sudo systemctl start surname-backend && curl -s http://127.0.0.1:8000/api/health
```

三天期间的回滚只需保证**能回到“数据完整 + 结构化查询可用”的状态**，不追求零停机。

## 10. 常见故障

| 现象 | 排查顺序 |
| --- | --- |
| 公网打不开但 `curl 127.0.0.1` 正常 | 安全组/防火墙 80 端口 → `nginx -t` → `ss -lntp` |
| `/api/health` 返回 503 | PostgreSQL 是否启动 → `DATABASE_URL` 是否正确 → 迁移是否执行 |
| 页面能开但接口 502 | systemd 服务是否在跑 → 后端日志 `journalctl -u surname-backend -n 100` |
| 中文乱码 | 数据库编码是否 UTF8 → Nginx 是否设置了 `charset utf-8` |
| 问答区一直“暂不可用” | Key 是否写入 `/etc/surname_app.env` → 服务器能否访问 DeepSeek 域名 |