# 未来 MCP 集成 README

## 当前建议

内部稳定工具先用 Python `@tool` 直接注册；MCP 用于用户自定义下载源、机构内网工具、独立 RAG 服务和跨项目复用。

## 推荐分层

```text
tools/builtins/      # 内置工具，直接 import
tools/community/     # 第三方 API 工具
tools/mcp/           # MCP client/server 管理
tools/rag_mcp/       # 可选 RAG MCP server
tools/registry.py    # 聚合工具
```

## extensions_config.json 示例

```json
{
  "mcpServers": {
    "institution-library": {
      "enabled": true,
      "type": "stdio",
      "command": "python",
      "args": ["/path/to/server.py"],
      "env": {"LIBRARY_TOKEN": "$LIBRARY_TOKEN"}
    }
  }
}
```

## Docker

stdio MCP 不需要单独容器，可在 Agent 容器内作为子进程启动；HTTP MCP 可单独容器或外部服务。
