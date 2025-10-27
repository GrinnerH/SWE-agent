# DeepSeek API 配置说明

## 已完成的配置

### 1. 修改了 `run_secb.sh` 脚本

添加了 `deepseek` 模型支持：
- 模型名称：`openai/deepseek-chat`
- API Base URL：`https://www.dmxapi.cn/v1`
- 使用 LiteLLM 的 OpenAI 兼容格式

### 2. 创建了 `.env` 文件

环境变量配置：
- **环境变量名**：`OPENAI_API_KEY`（项目标准变量）
- **用途**：存储 DeepSeek API Key

## 使用方法

### 步骤 1：配置 API Key

编辑 `.env` 文件，将 `your-deepseek-api-key-here` 替换为你的真实 API Key：

```bash
# 编辑 .env 文件
nano .env

# 或者使用 vim
vim .env

# 或者直接用命令替换
sed -i 's/your-deepseek-api-key-here/sk-your-actual-key/' .env
```

### 步骤 2：运行脚本

```bash
# 激活环境
conda activate sweagent

# 测试运行单个实例
./run_secb.sh poc -m deepseek -l :1

# 运行前 5 个实例
./run_secb.sh poc -m deepseek -l :5

# 运行前 10 个实例，2 个 worker 并行
./run_secb.sh poc -m deepseek -l :10 -w 2

# Patch 模式
./run_secb.sh patch -m deepseek -l :5
```

### 步骤 3：调整参数（可选）

```bash
# 提高 cost limit
./run_secb.sh poc -m deepseek -l :10 -c 3.0

# 增加调用次数限制
./run_secb.sh poc -m deepseek -l :10 -n 100

# 调整温度
./run_secb.sh poc -m deepseek -l :10 -e 0.7
```

## 配置详情

### API 配置
- **Base URL**：`https://www.dmxapi.cn/v1`
- **Model**：`deepseek-chat`
- **Provider**：`openai`（兼容格式）
- **环境变量**：`OPENAI_API_KEY`

### LiteLLM 格式
```
openai/deepseek-chat
```
这个格式告诉 LiteLLM：
- 使用 OpenAI 兼容的 API 格式
- 调用 `deepseek-chat` 模型
- 自动使用脚本中配置的 `api_base`

## 验证配置

### 检查环境变量
```bash
# 检查 .env 文件
cat .env | grep OPENAI_API_KEY

# 验证环境变量已加载（运行脚本后）
echo $OPENAI_API_KEY
```

### 测试运行
```bash
# 运行单个实例测试
./run_secb.sh poc -m deepseek -l 0:1 -c 1.0
```

如果看到类似输出，说明配置成功：
```
============================
Mode: poc
Model: deepseek (openai/deepseek-chat)
Config: ./config/secb_poc.yaml
Type: secb_poc
Cost Limit: 1.0
Temperature: 0.0
Split: eval
Slice: 0:1
Call Limit: 75
Workers: 1
API Base: https://www.dmxapi.cn/v1
```

## 故障排查

### 问题 1：API Key 无效
**错误**：`Authentication failed` 或 `Invalid API key`

**解决**：
- 确认 `.env` 文件中的 API Key 正确
- 确认 API Key 有效且未过期

### 问题 2：Base URL 连接失败
**错误**：`Connection refused` 或 `Timeout`

**解决**：
- 检查网络连接
- 确认 `https://www.dmxapi.cn/v1` 可访问
- 如果需要修改 Base URL，编辑 `run_secb.sh` 的第 105 行

### 问题 3：环境变量未加载
**错误**：脚本运行但没有使用 API Key

**解决**：
```bash
# 手动加载环境变量
export $(cat .env | grep -v '^#' | xargs)

# 或者使用 source（如果 .env 格式兼容）
set -a && source .env && set +a
```

## 高级配置

### 修改 Base URL（如果需要）

编辑 `run_secb.sh` 第 105 行：
```bash
elif [ "$model" == "deepseek" ]; then
    model_name="openai/deepseek-chat"
    api_base="https://your-custom-url.com/v1"  # 修改这里
```

### 使用不同的模型名称

如果你的代理支持其他 DeepSeek 模型：
```bash
# 编辑 run_secb.sh
model_name="openai/deepseek-coder"  # 或其他模型
```

### 直接使用命令行（不修改脚本）

```bash
sweagent run-batch \
    --num_workers 1 \
    --config ./config/secb_poc.yaml \
    --agent.model.name "openai/deepseek-chat" \
    --agent.model.api_base "https://www.dmxapi.cn/v1" \
    --agent.model.temperature 0.0 \
    --agent.model.per_instance_cost_limit 1.5 \
    --instances.type secb_poc \
    --instances.dataset_name "SEC-bench/SEC-bench" \
    --instances.split eval \
    --instances.slice :1
```

## 注意事项

1. **API Key 安全**：不要将 `.env` 文件提交到 Git
2. **Cost Limit**：DeepSeek 成本较低，可以适当提高 `-c` 参数
3. **并行请求**：使用 `-w` 参数时注意 API 速率限制
4. **环境变量优先级**：`.env` 文件 > 系统环境变量 > 命令行参数

## 参考资料

- [SWE-agent 官方文档](https://swe-agent.com/latest/)
- [LiteLLM 文档](https://docs.litellm.ai/docs/)
- [DeepSeek API 文档](https://platform.deepseek.com/api-docs/)
