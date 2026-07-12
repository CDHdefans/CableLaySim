# 安全说明

本项目按本地工程工作台设计，默认只监听 `127.0.0.1`，不需要公网服务、数据库或账号密钥。前端调用本机后端 API，后端计算结果写入本地 `backend/output/`。

## 本地运行边界

- 后端开发服务默认地址：`http://127.0.0.1:8765`
- 前端开发服务默认地址：`http://127.0.0.1:5173`
- 结果文件通过后端 `/api/files/<relative_path>` 读取，服务端会校验路径必须位于输出目录内。
- 不要把本项目直接部署到公网；如需部署，应先增加鉴权、限流、日志脱敏和 HTTPS 反向代理。

## 发布前检查

发布或二次分发前建议执行：

```powershell
git status --short
git check-ignore -v frontend/node_modules backend/output frontend/dist tmp .playwright-mcp
rg -n --hidden -g '!SECURITY.md' -g '!frontend/node_modules/**' -g '!frontend/dist/**' -g '!backend/output/**' "(api[_-]?key|secret|password|PRIVATE KEY|ghp_|github_pat_)" .
```

确认以下内容不会进入仓库：

- `frontend/node_modules/`
- `frontend/dist/`
- `backend/output/`
- `.playwright-mcp/`
- `tmp/`
- `.run/`
- `.env*`

## 依赖来源

前端依赖由 `frontend/package-lock.json` 锁定。首次运行脚本会执行 `npm ci`，从 npm registry 安装依赖。若所在网络访问 npm 较慢，可以自行配置 npm 镜像源。

## 报告问题

如果发现路径越界、意外暴露本地文件、异常大输出或依赖安全问题，请在仓库 Issue 中说明复现步骤、操作系统、Python/Node 版本和相关命令输出。
