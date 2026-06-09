# Docker 环境、代码开发与代码审查策略

## 当前状态

Dockerfile 是环境镜像，不复制业务代码。若直接运行 CLI，容器内会找不到 `backend`。需要在 compose 中挂载 `.:/app`，或在 Dockerfile 中添加 `COPY . /app`。

## 推荐 docker-compose

```yaml
services:
  pepclaw:
    build: .
    image: bioforge:local
    volumes:
      - ./:/app
      - ./.env:/app/.env
      - ./data:/app/data
      - ./v0_1PDF:/app/v0_1PDF
      - ./v0_1results:/app/v0_1results
    working_dir: /app
    stdin_open: true
    tty: true
```

## 开发流程

```bash
python verify_cli.py
python -m pytest backend/tests -v
python -m backend.src.cli --check-only
```

## 审查重点

- Graph：节点顺序、state patch、错误字段。
- Agent：plan/identity/skills/tools 是否一致。
- Tools：docstring、args_schema、结构化返回。
- DB：幂等初始化和写入。
- Trace：关键事件、payload 截断、run_id 贯通。

## 建议 Makefile

```makefile
install:
	pip install -r requirements.txt
check:
	python verify_cli.py
	python -m backend.src.cli --check-only
test:
	python -m pytest backend/tests -v
cli:
	python -m backend.src.cli
```
