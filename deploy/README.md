# deploy/ — 部署文件（E 主责，任务 E-05）

完整操作步骤见 [../docs/deployment.md](../docs/deployment.md)。本目录只放随代码走的配置。

| 文件 | 用途 | 目标位置（服务器） |
| --- | --- | --- |
| `nginx/surname_app.conf` | 静态托管前端 + 反代 `/api` + 限制 `/api/admin` 来源 IP | `/etc/nginx/sites-available/surname_app` |
| `systemd/surname-backend.service` | 后端进程托管、开机自启、异常自动重启 | `/etc/systemd/system/surname-backend.service` |

## 三步上线

```bash
# 1) 后端
cd /srv/surname_app/backend && python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
sudo cp /srv/surname_app/deploy/systemd/surname-backend.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now surname-backend

# 2) 前端
cd /srv/surname_app/frontend && npm ci && npm run build

# 3) 反向代理
sudo cp /srv/surname_app/deploy/nginx/surname_app.conf /etc/nginx/sites-available/surname_app
sudo ln -sf /etc/nginx/sites-available/surname_app /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 自检
curl -s http://127.0.0.1:8000/api/health
curl -s http://<公网IP>/api/health
```

## 上线前必须核对的安全项

- [ ] 安全组与 `ufw` 只放行 22 / 80 / 443；`ss -lntp | grep 5432` 为空（数据库不监听公网）
- [ ] `/etc/surname_app.env` 权限 600，密钥只存在于该文件
- [ ] `grep -r "DEEPSEEK\|sk-" frontend/dist` 无输出（前端不含任何密钥）
- [ ] `/etc/nginx/sites-available/surname_app` 中的 `allow` 名单已改为 B 与 C 的实际出口 IP
- [ ] 备份脚本已加入 cron，并手工验证过一次恢复

## 不做的事（三天阶段）

- 不配 HTTPS 与域名：先用公网 IP + HTTP 演示，域名、ICP 备案、HTTPS 属于期末工作。
- 不引入 Docker/K8s：三天内保持“脚本化部署”，让每个人都能读懂每一步。
- 不把数据库暴露到公网，即使临时排查也不开放。