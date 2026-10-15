# Python Sandbox MCP Server Setup Guide

This guide will help you set up the python sandbox MCP server integration within the MCP-Universe project.

### 1. Build the Docker Image

First, build the Docker image that will run the HTTP server inside the container:

```bash
docker build -f docker/python_code_sandbox/Dockerfile.server -t python-code-sandbox:latest .
```



### 2. Start the Container Manually

Start the Docker container manually with the following command:

```bash
docker run -d \
  --name python-sandbox-server \
  -p 18080:8080 \
  -e SANDBOX_PORT=8080 \
  -e SANDBOX_TEMP_DIR=/tmp/sandbox_executions \
  --memory=100g \
  --cpus=20 \
  python-code-sandbox:latest
```

**Verify the container is running:**
```bash
docker logs -f --tail 10 python-sandbox-server
```